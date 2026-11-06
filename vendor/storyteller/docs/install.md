# Installing Storyteller on a FastAPI app

Time: about 15 minutes. You need Docker (or Python 3.11+) for the service, and an LLM key or a local model.

## What you're adding

- **Snippet**: one `<script>` tag on your pages. Inert until you call `storyteller.start()`.
- **Service**: one container running next to your app. Receives events, writes stories.
- **Two routes in your app**: where stories are written and where visitor memory is read from. The reference adapter in `packages/adapters/fastapi/` implements both with SQLite and includes a viewer page.

## 1. Add the adapter to your app

Copy `packages/adapters/fastapi/storyteller_adapter.py` and `viewer.html` into your project (same directory), then:

```python
from storyteller_adapter import make_router

app.include_router(make_router(db_path="storyteller.db"))
# routes created: POST /internal/storyteller/stories, GET /internal/storyteller/visitors/{id},
#                 GET  /internal/storyteller/ui  (the viewer; put it behind your admin auth)
```

Set `STORYTELLER_SECRET` in your app's environment (any long random string). The adapter rejects any request not signed with it.

Want different routes? `make_router(prefix="/wherever")` and set the same paths in the service config below. Want your own storage? Copy the two route functions and replace `Store` with your own calls; the request/response schemas are in `docs/protocol.md`.

## 2. Run the service

Create a folder next to your deployment, e.g. `storyteller-config/`, with:

`storyteller.yaml`:
```yaml
site:
  key: pick-a-random-string           # snippet sends this
  allowed_origins: ["https://your-site.com"]
  brief_file: brief.md
recording:
  default_enabled: false              # flip on with the API below
  idle_timeout_minutes: 10
llm:
  provider: anthropic                 # or openai_compatible
  api_key_env: LLM_API_KEY
  model: claude-sonnet-4-5            # or gpt-4o-mini, or a local model name
  # for Ollama/vLLM/internal gateways:
  # provider: openai_compatible
  # base_url: http://ollama:11434/v1
consumer:
  base_url: http://app:8000           # your app, as reachable from the service container
  routes:
    write_story: /internal/storyteller/stories
    read_visitor: /internal/storyteller/visitors/{id}
  secret_env: STORYTELLER_SECRET
service:
  prefix: /storyteller
  admin_token_env: STORYTELLER_ADMIN_TOKEN
  buffer_dir: /data
```

`brief.md`: copy `examples/brief.example.md` and rewrite it for your site. This is the single most important input: what the site is, who uses it, what success looks like per page, known trouble spots, recent changes, and a tag vocabulary.

Then in your `docker-compose.yml`:
```yaml
  storyteller:
    image: ghcr.io/you/storyteller:latest    # or build: ./storyteller
    volumes:
      - ./storyteller-config:/config:ro
      - storyteller-data:/data
    environment:
      STORYTELLER_SECRET: ${STORYTELLER_SECRET}        # same value as your app
      STORYTELLER_ADMIN_TOKEN: ${STORYTELLER_ADMIN_TOKEN}
      LLM_API_KEY: ${LLM_API_KEY}
    ports: ["8787:8787"]
```

No Docker? `pip install ./packages/service && storyteller serve --config storyteller-config/storyteller.yaml --port 8787`.

Check it: `curl http://localhost:8787/storyteller/health` should show `"ok": true` and `consumer.check.ok: true`. If the hook check fails, the service can't reach your app at `consumer.base_url` or the secrets differ.

## 3. Expose the service to browsers

The snippet needs to reach `POST /storyteller/events` and `GET /storyteller/recording`. Two options:

- **Reverse-proxy it under your domain** (recommended): route `https://your-site.com/storyteller/*` to the service on 8787. Same-origin, no CORS concerns.
- **Or a subdomain**, e.g. `https://storyteller.your-site.com`, and set `allowed_origins` to your site.

## 4. Add the snippet

Serve `packages/snippet/dist/storyteller.js` from your static files (it's ~80 KB, no dependencies), then on every page:

```html
<script src="/static/storyteller.js" defer></script>
<script>
  window.addEventListener("DOMContentLoaded", () => {
    storyteller.init({ endpoint: "/storyteller", siteKey: "pick-a-random-string" });
    storyteller.start();              // call this only once you have whatever consent you need
  });
</script>
```

After login: `storyteller.identify(userId, { plan: "pro" })` — links this browser's visits to your user id and passes facts into the story.

Sensitive areas: add `data-no-record` to any element whose contents must never be captured. Typed input is always masked regardless.

## 5. Turn recording on

```bash
curl -X POST http://localhost:8787/storyteller/recording \
  -H "Authorization: Bearer $STORYTELLER_ADMIN_TOKEN" -d '{"enabled": true}'
```
Same call with `false` stops every snippet within five minutes and makes the service refuse events. Do this from code whenever you like.

## 6. Watch stories arrive

Browse your site, leave the tab, wait `idle_timeout_minutes` (or call `storyteller.end()` from the console to end the visit now). Within about 30 seconds the story is POSTed to your app. Open `/internal/storyteller/ui`.

Stories are also plain rows in `storyteller.db` (`stories.story` is the full JSON), so query them however you like.

## Tuning

- Stories off? Use the viewer's "tell Storyteller something" box, or `PUT /internal/storyteller/instructions/global` with `{"text": "..."}`. Takes effect on the next visit.
- Edit `brief.md` any time; the service re-reads it per visit. Or `PUT /storyteller/brief` with the admin token.
- Re-run an old visit under new instructions: `POST /storyteller/visits/{id}/regenerate` with `{"timeline": <story.timeline fields>}` or `{"recording": <raw events>}`.
- Signal thresholds live under `timeline.signals` in the config.

## Testing without a key

`docker compose --profile demo up` runs the service with a fake LLM and a demo consumer. Open `http://localhost:8000/internal/storyteller/ui`, then serve `examples/demo-site` on any port (e.g. `python -m http.server 8080 -d examples/demo-site`) with `window.__ST_ENDPOINT = "http://localhost:8787/storyteller"` set before the snippet loads, click around, and watch stories appear.
