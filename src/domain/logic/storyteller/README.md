# Storyteller: the consumer side

[Storyteller](../../../../vendor/storyteller/README.md) is a self-hosted sidecar that records how people use the site, turns each visit into a deterministic timeline, and has an LLM write a short plain-language story of the visit. It is a pipe, not a database: every story is POSTed back to this app, and the per-visitor memory the next story is written from is read back from this app. This directory is that consumer side; the service itself runs as its own container (see [`deployment/README.md`](../../../../deployment/README.md)).

The library's protocol is the contract — [`vendor/storyteller/docs/protocol.md`](../../../../vendor/storyteller/docs/protocol.md) for the two hooks and the signing scheme, [`docs/story.schema.json`](../../../../vendor/storyteller/docs/story.schema.json) for the Story shape. Nothing here restates them.

## How it's wired

- **Two auth schemes on one prefix.** [`../../routes/storyteller.py`](../../routes/storyteller.py) mounts everything under `/internal/storyteller`. The two hooks the *service* calls (`POST /stories`, `GET /visitors/{id}`) are authenticated by the HMAC the service signs each request with, keyed on `STORYTELLER_SECRET` — no cookie, no fastapi-users. The viewer (`GET /ui`) and the routes it calls (`/recent`, `/visitors/{id}/facts`, `/instructions/{scope}`) are for a signed-in superuser and take `current_admin_user`, so the anonymous→login / non-admin→403 ladder is the same as `/admin/*`.
- **Stories live in their own SQLite file**, `settings.STORYTELLER_DB_PATH` (default `data/storyteller.db`, the persisted volume in prod), not in the app DB and not under Alembic. The story schema is versioned by the library; keeping it as plain rows with the full JSON in `stories.story` means a library upgrade never needs an app migration, and the data can be queried with any `sqlite3` client. [`adapter.py`](adapter.py) owns the tables; `Store` is lazy, so booting the app never touches the file.
- **`STORYTELLER_SECRET` unset → the hooks answer 503**, not 401: a misconfigured deploy fails loudly on the service's startup hook check instead of looking like a forged caller. The viewer still works (it just shows nothing).
- **The read hook's 404 means "new visitor".** The service then writes the story without history. Facts an admin adds *before* the visitor's first story make them known.

## Vendoring

[`adapter.py`](adapter.py) and [`viewer.html`](viewer.html) are adapted copies of the library's reference adapter (`vendor/storyteller/packages/adapters/fastapi/`). Deliberate differences from upstream, so a future re-sync knows what to keep:

- Route functions moved to `src/domain/routes/storyteller.py` so the admin-only routes can take a FastAPI dependency; upstream's `make_router` leaves them unprotected ("protect them as you see fit").
- `Store` creates its schema lazily and `mkdir`s the parent directory; upstream does both in `__init__`.
- Secret and DB path come from `settings`, read per request (so tests can monkeypatch), not from `os.environ` at mount time.
- `add_fact` rejects empty text with 422; upstream stores it.

**Local patches to `vendor/storyteller/` itself** (apply upstream when syncing, or drop once upstream has them):

- `packages/service/storyteller/config.py`: no default `llm.base_url`. The shared OpenAI default leaked into the Anthropic brain whenever `provider: anthropic` was set without a `base_url`, sending stories to `api.openai.com/v1/v1/messages`. Pinned by `packages/service/tests/test_config.py`.

The browser snippet at `src/framework/static/js/storyteller.js` is a verbatim copy of `vendor/storyteller/packages/snippet/dist/storyteller.js`. To upgrade either, re-copy from `vendor/storyteller/` after updating it, then re-apply the list above.

## The snippet

`base.html` renders the snippet on every page iff `STORYTELLER_SITE_KEY` is set (`storyteller_frontend` in the template context, same switch shape as `observability_frontend`). It `init`s with `STORYTELLER_ENDPOINT`, calls `identify(<user id>)` for signed-in viewers so stories can name the member, then `start()`. Rendering the tag is not recording: `start()` first asks the service whether recording is on, and the service's kill switch is off by default — turning it on is the deployment's call ([`deployment/README.md § Storyteller`](../../../../deployment/README.md)). Typed input is always masked; mark any element whose text must never leave the browser with `data-no-record`.

**Trying it locally without Docker.** Run the app with `STORYTELLER_SECRET=<x> STORYTELLER_SITE_KEY=<k> STORYTELLER_ENDPOINT=http://localhost:8787/storyteller`, then from a Python 3.12 venv: `pip install vendor/storyteller/packages/service` and `storyteller serve --config <your.yaml> --port 8787`, where the yaml copies `vendor/storyteller/storyteller.example.yaml` with `site.key: <k>`, `consumer.base_url: http://localhost:8000`, `recording.default_enabled: true`, and either a real LLM or `vendor/storyteller/examples/fake_llm.py` (`uvicorn fake_llm:app --port 8010`, `llm.base_url: http://localhost:8010/v1`). Start the service *after* the app: its hook check runs once at startup and `/storyteller/health` reports that result until the next restart.

## Tests

Colocated. [`test_adapter.py`](test_adapter.py) pins the signature scheme against the protocol and the store's read-hook shape; [`../../routes/test_storyteller.py`](../../routes/test_storyteller.py) pins the two auth ladders and the healthcheck/404 protocol behaviours, with the store pointed at a temp file via `dependency_overrides`.
