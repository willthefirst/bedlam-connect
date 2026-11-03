# Admin data: Datasette observability queries

The admin's Datasette at `/admin/data/` (superusers only) — saved SQL queries over the live app DB that implement the launch plan's Observability spec. The daily queries list each case to act on, the weekly queries show the hot spots, and the drill-downs explain one week, post, or person. The query list itself lives in [`metadata.yaml`](metadata.yaml); add a question by adding a query there, not a new page.

## How it's wired

- **Auth is the normal admin dependency.** [`../../routes/admin.py`](../../routes/admin.py) declares a catch-all `GET|POST /admin/data/{path}` route that depends on `current_admin_user`, then returns `DatasetteResponse`, which hands the untouched ASGI scope/receive to Datasette. It is a route, not `app.mount(...)`, because a mounted ASGI app can't take FastAPI `Depends` — mounting would mean re-implementing cookie/JWT auth on raw ASGI. Datasette routes off the full path and strips its own `base_url` (`/admin/data/`).
- **The signed-in admin is Datasette's actor.** The route puts `{"id": <user hex>, ...}` on the ASGI scope; the plugin hook in [`datasette_app.py`](datasette_app.py) returns it from `actor_from_request`, so the "Add a note" query stamps `author_id` via `:_actor_id`.
- **One process-wide Datasette, signed with the app `SECRET`.** Built lazily by `get_admin_data_app` (the dependency tests override). The shared secret keeps CSRF tokens valid across restarts and the blue/green switch.
- **Read-only except one query.** Datasette opens read connections `mode=ro`, so ad-hoc SQL can't write. The only write is the `add_note` canned query, which inserts into `admin_notes` — a table the app never reads, so the `AdminNote` CHECKs are its only validation. `sql_time_limit_ms` sits under nginx's 10 s proxy timeout.

## Shared definitions are SQL views

The queries build on views created in migration `37ea65ccbf12`: `member_names`, `post_summaries`, `member_onboarding`, `connection_verdicts`, and `post_outcomes` (the one definition of a "good" post). They exist **only in the migration** — the app's ORM metadata doesn't know them — so changing one is a new migration that drops and recreates it. `member_onboarding` restates `onboarding_readiness()` in SQL; [`test_views.py`](test_views.py) pins the two together.

Connections are `post_connections` rows; every message sent is a `send_post_message` audit row against its connection (see [`../../../framework/audit/README.md`](../../../framework/audit/README.md)). Message bodies are never stored.

[`sql_functions.py`](sql_functions.py) registers display helpers (`ago`, `when_at`, `week_label`) on Datasette's connections — Pacific-time relative ages instead of raw UTC text. Views don't use them, so the views stay queryable from a plain `sqlite3` shell.

## Dashboards

Charts and number tiles come from the `datasette-dashboards` plugin, configured under `plugins:` in the same `metadata.yaml` and served at `/admin/data/-/dashboards` (Datasette's menu links it). Each chart is SQL plus a Vega-Lite spec; the plugin bundles Vega, so nothing loads from a CDN. Charts read the shared views — they never restate a daily query's to-do logic, since the daily queries *are* the to-do lists.

**Never give a dashboard filter a `default:`.** The plugin then redirects a bare visit to `?<filter>=<default>` and copies every request cookie onto the redirect through Datasette's `set_cookie`, which reissues our session cookie without HttpOnly/Secure. [`test_dashboard.py`](test_dashboard.py) fails on any default, and the route test asserts the dashboard sets no cookies.

## Tests

Colocated. They run against a migrated temp *file* DB (`migrate_sqlite_file` in [`../../../../tests/helpers.py`](../../../../tests/helpers.py)) because the default in-memory test DB has no views and Datasette can't open it. [`test_queries.py`](test_queries.py) runs each saved query's SQL straight from `metadata.yaml`; the route-level auth ladder and the end-to-end "Add a note" POST live in [`../../routes/test_admin_data.py`](../../routes/test_admin_data.py).
