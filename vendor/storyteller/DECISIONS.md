# Decisions

- **Python DOM mirror instead of a Node sidecar for replay.** `timeline/dom.py` applies rrweb snapshots and mutations in ~200 lines. One runtime, one container, no Node in production. Revisit if canvas/shadow-DOM-heavy sites need rrweb's own replayer.
- **Screenshots deferred.** The pipeline runs without them; `Image` support is in the brain interface and the story schema. Add in v1.1 with Playwright rendering of the serialized snapshot.
- **Snippet flushes with `fetch(keepalive)` first, `sendBeacon` as fallback.** Both survive unload; keepalive is routable in tests.
- **Visit = snippet-side id continued across page loads while idle < timeout; the service finalizes on `visit_end` or idle timeout.** Simple, no server-side session stitching.
- **Stories that fail delivery are appended to `<buffer_dir>/stories.jsonl`.** Never lose a story because the consumer was down.
- **Brief carries tags and instructions as `## Tags` / `## Instructions` sections.** One file to edit, no extra config keys.
- **Package name `storyteller-web` on PyPI, `@storyteller/snippet` on npm** (bare `storyteller` is taken). Project name stays Storyteller.
- **Error detection v0 is class/role/text heuristics** (`error|invalid|alert|toast`, `role=alert`, "required|invalid|failed"). Good enough on the fixtures; expect to tune per site.
- **Reference adapter ships a viewer page.** It's a convenience, not the product; the SQLite tables are the real interface.
