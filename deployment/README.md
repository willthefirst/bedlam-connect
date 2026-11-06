# Deployment

Blue-green deploys to a DigitalOcean droplet, driven by [`.github/workflows/cd.yml`](../.github/workflows/cd.yml).

- `droplet-files/` — synced to `/opt/bedlam-connect/deployment/` on the droplet.
- `scripts/` — helper scripts run by CI (e.g. `deploy-copy-files.sh`).

`ls deployment/droplet-files/` and `ls deployment/scripts/` are the source of truth for what's there.

## Pipeline

`.github/workflows/cd.yml` has two jobs:

1. `build-and-push` — builds the image from [`docker/Dockerfile`](docker/Dockerfile) and pushes to GHCR.
2. `deploy` — runs `scripts/deploy-copy-files.sh` to SCP `droplet-files/*` to `/opt/bedlam-connect/deployment/`, then SSHes in and runs `./deploy.sh`.

`deploy.sh` implements the blue-green switch: detect current color, start the alternate (blue on `:8001`, green on `:8002`), health-check it, point nginx at it, drop the old. Read [`cd.yml`](../.github/workflows/cd.yml) and `droplet-files/deploy.sh` for the exact steps.

## Bootstrapping an admin

Admin actions require `is_superuser=True`; no admin exists out of the box. Promote a registered user via the wrapper deployed alongside `deploy.sh`:

```bash
ssh user@your-droplet-ip
cd /opt/bedlam-connect/deployment
./promote-admin.sh you@example.com           # grant
./promote-admin.sh you@example.com --revoke  # revoke
```

The wrapper auto-detects the running blue/green container, is idempotent, and refuses on a missing user. Locally, the equivalent is `dev promote-admin <email>`.

## Manual deploy (emergency)

If CI fails:

```bash
ssh user@your-droplet-ip
cd /opt/bedlam-connect/deployment
# Re-copy files only if needed:
# scp deployment/droplet-files/* user@droplet-ip:/opt/bedlam-connect/deployment/
chmod +x deploy.sh cleanup-docker.sh
./deploy.sh
```

`./deploy.sh` is idempotent — re-running it after a failure rolls back to the working color.

## Storyteller sidecar

[Storyteller](../vendor/storyteller/README.md) runs as a third container, `storyteller`, next to the blue/green pair. `cd.yml` builds its image from `vendor/storyteller/` as `ghcr.io/willthefirst/bedlam-connect-storyteller`; `deploy.sh`'s `deploy_storyteller` pulls and `up -d`s it after the app switch, best-effort (a sidecar failure never fails the app deploy). Its config and site brief live in `droplet-files/storyteller/` and ride the normal SCP sync; edit `brief.md` there and push — the service re-reads it per visit. The consumer side (the hooks it calls, the admin viewer) is documented in [`../src/domain/logic/storyteller/README.md`](../src/domain/logic/storyteller/README.md).

**Secrets.** Four optional GitHub secrets land in the shared `.env`: `STORYTELLER_SECRET` (HMAC key both containers share), `STORYTELLER_ADMIN_TOKEN` (the service's admin API), `STORYTELLER_SITE_KEY` (public; rendered into the snippet and checked by the service, written once as both `STORYTELLER_SITE_KEY` and `ST_SITE__KEY`), `STORYTELLER_LLM_API_KEY` (Anthropic key; written as `LLM_API_KEY`). All empty → no snippet on pages, hooks 503, sidecar idle.

**Exposure.** The container binds `127.0.0.1:8787`; nginx proxies only `POST /storyteller/events` and `GET /storyteller/recording` (the two the snippet needs). Health, brief and the kill switch are host-local:

```bash
ssh user@your-droplet-ip
curl -s localhost:8787/storyteller/health | jq .consumer.check        # must show ok: true
curl -X POST localhost:8787/storyteller/recording \
  -H "Authorization: Bearer $(grep STORYTELLER_ADMIN_TOKEN /opt/bedlam-connect/config/.env | cut -d= -f2)" \
  -H "Content-Type: application/json" -d '{"enabled": true}'          # false to stop everything
```

Recording is off by default (`recording.default_enabled: false`); the flag persists in `/opt/bedlam-connect/storyteller-data/recording.json` across restarts. Stories arrive at the app's `/internal/storyteller/ui` (superusers).

## Host cron

`droplet-files/cleanup-docker.sh` is the host-cron rail (prunes container layers outside the app process). Jobs that need app rails (`async_session_maker`, audit, domain handlers) go through APScheduler — see [`../src/jobs/README.md`](../src/jobs/README.md).
