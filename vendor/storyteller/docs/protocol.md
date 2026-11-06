# Consumer protocol (v1)

Storyteller talks to your app through two functions. You choose the URLs; the methods, headers and JSON shapes are fixed.

## Signing

Every request from the service carries:

```
X-Storyteller-Timestamp: <unix seconds>
X-Storyteller-Signature: v1=<hex hmac_sha256(secret, "<timestamp>.<raw body>")>
```
For GET requests the body is the empty string. Reject if the timestamp is more than 300 s from now or the HMAC doesn't match. `packages/adapters/fastapi/storyteller_adapter.py` has `verify_signature()`.

## write_story — `POST <your route>`

Body: a Story (`docs/story.schema.json`). Return any 2xx. On failure the service retries 3× with backoff, then appends the story to `<buffer_dir>/stories.jsonl` so nothing is lost.

On startup the service also POSTs `{"schema_version": "1", "healthcheck": true}`; return 2xx without storing it.

Key fields:

| field | meaning |
|---|---|
| `visit_id`, `visitor_id`, `user_id` | visit; anonymous browser id; your id if `identify()` was called |
| `narrative` | 3–8 sentences, the story |
| `outcome` | `{label, observed, inferred, confidence}` |
| `tags[]` | lowercase slugs |
| `friction[]` | `{at, evidence, inference, confidence}` per moment of trouble |
| `observations[]`, `suggestions[]` | plain notes; optional concrete suggestions with confidence |
| `visitor_summary` | what we now think about this person across visits |
| `trajectory[]` | prior visits + this one: `{visit_id, started_at, outcome, friction[]}` (max 20) |
| `timeline[]`, `timeline_text` | the deterministic timeline the story was written from |
| `history_available` | whether the read hook returned memory for this visitor |
| `consent`, `device`, `pages`, `referrer`, `started_at`, `ended_at`, `duration_s`, `entry_url` | context |
| `provenance` | `{model, prompt_version, generated_at, input_tokens, output_tokens, attempts}` |

## read_visitor — `GET <your route with {id}>`

Called before writing a story. Return 404 for an unknown visitor, or:

```json
{
  "schema_version": "1",
  "summary": "last story's visitor_summary",
  "trajectory": [{"visit_id": "...", "started_at": "...", "outcome": "...", "friction": ["..."]}],
  "facts": [{"text": "This is my friend Sam", "weight": "high", "added_at": 1730851200}],
  "instructions": {"global": "Be skeptical about idle time.", "visitor": "Sam is an expert."}
}
```
All fields optional. `weight: high` facts are stated as true in the narrative. Instructions are writing preferences; they cannot override the storyteller's evidence rules. If the hook times out or errors, the story is written without history and `history_available` is false.

Minimum viable implementation: store each story; on read, return the latest story's `visitor_summary` and `trajectory` for that `visitor_id`, plus whatever facts/instructions you've saved.

## Service endpoints (prefix configurable, default `/storyteller`)

| route | method | auth | purpose |
|---|---|---|---|
| `/events` | POST | site key in body | event chunks from the snippet; 403 when recording is off |
| `/recording` | GET | none | `{enabled}` — the snippet asks this before recording |
| `/recording` | POST | admin token | `{enabled: bool}` kill switch, persisted |
| `/brief` | GET/PUT | admin token | the site brief |
| `/visits/{id}/regenerate` | POST | admin token | `{recording}` or `{timeline}`, optional `history`, `deliver` (default true) |
| `/health` | GET | none | status, hook check, config summary |

Admin auth: `Authorization: Bearer <STORYTELLER_ADMIN_TOKEN>`.
