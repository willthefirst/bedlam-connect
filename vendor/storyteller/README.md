# Storyteller

A self-hosted service that watches how real people use your website and writes a plain-language story of each visit: what they did, how it went, where they struggled, grounded in what actually happened on screen. Like notes from a friend who sat beside the visitor.

- **Drop in**: one script tag, one container, two small routes in your app.
- **Your LLM**: bring a key (OpenAI, Anthropic) or point it at a local model. Nothing else leaves your infrastructure.
- **Your data**: Storyteller is a pipe, not a database. Stories are POSTed to your app as structured JSON; visitor memory is read back from your app. Query it however you like.
- **Honest**: every story separates what was observed from what is inferred, with confidence and timestamps.
- **Default off**: records nothing until you call `start()`; one API call turns everything off.

```
Browser snippet ──events──▶ Story service ──story JSON──▶ your app (write hook)
   (rrweb)                  timeline → LLM ◀──memory──── your app (read hook)
```

## Try it in 2 minutes (no API key)

```bash
docker compose --profile demo up --build
# viewer:   http://localhost:8000/internal/storyteller/ui
# service:  http://localhost:8787/storyteller/health
python -m http.server 8080 -d examples/demo-site   # then browse it with window.__ST_ENDPOINT="http://localhost:8787/storyteller"
```

Or without Docker, straight from a recording:
```bash
pip install ./packages/service
storyteller timeline fixtures/compare_abandon.json        # the deterministic timeline
LLM_API_KEY=sk-... storyteller story fixtures/compare_abandon.json --brief examples/brief.example.md --config storyteller.example.yaml   # needs a key, or point llm.base_url at examples/fake_llm.py
```

Example timeline (real recording of the demo site):
```
t=0s         page /pricing.html (from www.google.com)
t=2s       ~ back-and-forth between area "Pro plan" and area "Team plan" ×3 (16s)
t=18s        click button "Annual"
t=18s      > text changed in "Pro plan" section: "$29/mo" → "$290/yr"
t=26s        click button "Start trial" in "Pro plan"
t=26s        page /signup.html?plan=pro
t=28s        focus field "Email"
t=31s        typed in field "Email" (19 chars, masked)
t=33s        focus field "Company name"
t=33s      ~ still on field "Company name", no input (9s)
t=42s      # tab hidden
t=42s      ~ away from tab for 12s
t=56s        click button "Create account"
t=56s      > error shown: "Company name is required"
t=60s      ~ clicked button "Create account" again; same error still shown
t=1m03s    ~ left with a form partly filled (2 fields); last error: "Company name is required"
```

## Install on your app

See **[docs/install.md](docs/install.md)** (FastAPI, ~15 minutes). Protocol: [docs/protocol.md](docs/protocol.md). LLM adapters: [docs/brains.md](docs/brains.md). Privacy: [docs/privacy.md](docs/privacy.md). Story schema: [docs/story.schema.json](docs/story.schema.json).

## Layout

```
packages/snippet/            browser snippet (TypeScript → dist/storyteller.js)
packages/service/            the service: timeline/, story/, llm/, api.py, cli.py
packages/adapters/fastapi/   reference consumer: two routes + SQLite + viewer
examples/                    demo site, fixture recorder, demo consumer, fake LLM, example brief
fixtures/                    real rrweb recordings of the demo site
docs/                        install, protocol, brains, privacy, schema
```

## Develop

```bash
cd packages/snippet && npm install && npm run build
cd packages/service && pip install -e '.[dev]' && python -m playwright install chromium && pytest
python examples/record_fixtures.py        # re-record fixtures (~90 s, real timing)
```

## Status

v0/v1: timeline, storyteller, brains, service, kill switch, hooks, reference adapter, viewer, Docker. Tested end to end with a real browser and a fake LLM. Screenshots, a second adapter (Express), and the tested-models table are next. See `DECISIONS.md`.

MIT.
