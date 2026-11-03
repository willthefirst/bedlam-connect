"""The admin's Datasette instance — saved observability queries over
the live SQLite DB, served under `/admin/data/` behind
`current_admin_user` (see `src/domain/routes/admin.py`).

Datasette is an ASGI app. Rather than `app.mount(...)` it (which can't
take FastAPI `Depends`, so auth would have to be re-implemented on raw
ASGI), the admin route authorizes the request with the normal
superuser dependency and then hands the untouched ASGI scope/receive
to Datasette via `DatasetteResponse`. The authorized user rides along
on the scope; the plugin below turns it into the Datasette actor, so
the "Add a note" query can stamp `:_actor_id`.

Read-only by construction: Datasette opens its read connections with
`mode=ro`, so ad-hoc SQL can't write. The only write path is the
`add_note` canned query, and it only inserts into `admin_notes`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from datasette import hookimpl
from datasette.app import Datasette
from datasette.database import Database
from datasette.plugins import pm
from sqlalchemy.engine import make_url
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from src.domain.logic.admin_data.sql_functions import register_sql_functions
from src.framework.config import settings

BASE_URL = "/admin/data/"
DATABASE_NAME = "bedlam"
METADATA_PATH = Path(__file__).with_name("metadata.yaml")

# Scope key the admin route sets to the authorized superuser's actor
# dict; read back by `actor_from_request` below.
ACTOR_SCOPE_KEY = "bedlam.admin_actor"

# Well under nginx's 10s `proxy_read_timeout` (deploy.sh), so a slow
# query fails inside Datasette with a readable error, not a 504.
_SQL_TIME_LIMIT_MS = 3000


@hookimpl
def actor_from_request(datasette, request):
    return request.scope.get(ACTOR_SCOPE_KEY)


@hookimpl
def prepare_connection(conn):
    register_sql_functions(conn)


_PLUGIN_NAME = "bedlam_admin_data"
if not pm.has_plugin(_PLUGIN_NAME):
    pm.register(sys.modules[__name__], name=_PLUGIN_NAME)


def load_metadata() -> dict[str, Any]:
    return yaml.safe_load(METADATA_PATH.read_text())


def sqlite_path_from_url(url: str) -> str:
    """`sqlite+aiosqlite:///data/x.db` → `data/x.db`."""
    database = make_url(url).database
    if not database or database == ":memory:":
        raise ValueError(f"Datasette needs a file-backed SQLite DB, got {url!r}")
    return database


def build_datasette(db_path: str) -> Datasette:
    ds = Datasette(
        # Datasette signs its CSRF tokens with this. The app secret (not
        # Datasette's per-process random default) keeps an open "Add a
        # note" form valid across restarts and the blue/green switch.
        secret=settings.SECRET,
        metadata=load_metadata(),
        settings={
            "base_url": BASE_URL,
            "sql_time_limit_ms": _SQL_TIME_LIMIT_MS,
        },
    )
    # Fixed name (not the file stem) so `metadata.yaml` keys and URLs are
    # the same in dev, prod, and tests.
    ds.add_database(Database(ds, path=db_path, is_mutable=True), name=DATABASE_NAME)
    if "_memory" in ds.databases:
        ds.remove_database("_memory")
    return ds


_app: ASGIApp | None = None


def get_admin_data_app() -> ASGIApp:
    """FastAPI dependency: the process-wide Datasette ASGI app over the
    app DB, built on first use (Datasette runs its own startup on the
    first request it serves). Tests override it with one pointed at a
    temp-file DB built by the migrations."""
    global _app
    if _app is None:
        _app = build_datasette(sqlite_path_from_url(settings.DATABASE_URL)).app()
    return _app


class DatasetteResponse(Response):
    """Hands the request's raw ASGI scope/receive to Datasette.

    The route never reads the body, so `receive` is still unconsumed
    and Datasette's form POSTs (with their CSRF tokens) arrive intact.
    """

    def __init__(self, app: ASGIApp, actor: dict[str, Any]) -> None:
        super().__init__()
        self._app = app
        self._actor = actor

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._app({**scope, ACTOR_SCOPE_KEY: self._actor}, receive, send)
