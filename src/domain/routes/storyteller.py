"""Storyteller consumer routes: the two signed hooks + the admin viewer.

    POST /internal/storyteller/stories             write hook   (HMAC-signed)
    GET  /internal/storyteller/visitors/{id}       read hook    (HMAC-signed)
    GET  /internal/storyteller/ui                  viewer       (superuser)
    GET  /internal/storyteller/recent              viewer data  (superuser)
    POST /internal/storyteller/visitors/{id}/facts               (superuser)
    PUT  /internal/storyteller/instructions/{scope}              (superuser)

Two callers, two auth schemes. The Storyteller *service* calls the two
hooks and proves itself with the shared `STORYTELLER_SECRET` (an HMAC
over timestamp + raw body; see `vendor/storyteller/docs/protocol.md`),
so those routes take no cookie and never touch fastapi-users. The
viewer and its conveniences are for a signed-in admin, so they ride the
normal `current_admin_user` dependency — anonymous browsers get the
global 401→login redirect, non-superusers 403.

Hand-written (not an `EntitySpec`): the hooks are a fixed external
protocol, not a resource with a CRUD face. Follows the bespoke-route
pattern in `src/domain/routes/README.md § Bespoke routes`. Storage and
the signature check live in `src/domain/logic/storyteller/adapter.py`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src.auth_config import current_admin_user
from src.domain.logic.storyteller.adapter import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    Store,
    verify_signature,
)
from src.framework.config import settings

PREFIX = "/internal/storyteller"
_VIEWER_PATH = Path(__file__).parents[1] / "logic" / "storyteller" / "viewer.html"

storyteller_router = APIRouter(prefix=PREFIX, tags=["storyteller"])


@lru_cache(maxsize=1)
def get_storyteller_store() -> Store:
    """One process-wide store at `settings.STORYTELLER_DB_PATH`. Tests
    override this dependency with a store on a temp path."""
    return Store(settings.STORYTELLER_DB_PATH)


async def _signed_body(request: Request) -> bytes:
    """Read the raw body and verify the service's signature over it.

    503 when the app has no `STORYTELLER_SECRET` (misconfiguration, not a
    bad caller); 401 on a missing/stale/forged signature.
    """
    body = await request.body()
    secret = settings.STORYTELLER_SECRET
    if not secret:
        raise HTTPException(503, "STORYTELLER_SECRET not set")
    if not verify_signature(
        secret,
        request.headers.get(TIMESTAMP_HEADER, ""),
        body,
        request.headers.get(SIGNATURE_HEADER, ""),
    ):
        raise HTTPException(401, "bad signature")
    return body


# ---- the two protocol hooks (called by the service) -----------------------


@storyteller_router.post("/stories", name="storyteller:write_story")
async def write_story(
    body: bytes = Depends(_signed_body),
    store: Store = Depends(get_storyteller_store),
) -> dict[str, Any]:
    story = json.loads(body)
    # The service POSTs `{"schema_version": "1", "healthcheck": true}` at
    # startup to prove the hook is reachable; acknowledge without storing.
    if story.get("healthcheck"):
        return {"ok": True, "healthcheck": True}
    store.save_story(story)
    return {"ok": True}


@storyteller_router.get("/visitors/{visitor_id}", name="storyteller:read_visitor")
async def read_visitor(
    visitor_id: str,
    _: bytes = Depends(_signed_body),
    store: Store = Depends(get_storyteller_store),
) -> Any:
    visitor = store.visitor(visitor_id)
    if visitor is None:
        # 404 is the protocol's "new visitor"; the service then writes the
        # story without history.
        return JSONResponse({"error": "unknown visitor"}, status_code=404)
    return visitor


# ---- admin conveniences (the viewer and what it calls) --------------------


@storyteller_router.get(
    "/ui",
    name="storyteller:ui",
    response_class=HTMLResponse,
    dependencies=[Depends(current_admin_user)],
    include_in_schema=False,
)
async def ui() -> str:
    # The viewer is the library's standalone page (not a `base.html`
    # child); it only needs to know where its own data routes live.
    return _VIEWER_PATH.read_text().replace("__PREFIX__", PREFIX)


@storyteller_router.get(
    "/recent",
    name="storyteller:recent",
    dependencies=[Depends(current_admin_user)],
)
async def recent(
    limit: int = 50, store: Store = Depends(get_storyteller_store)
) -> list[dict[str, Any]]:
    return store.recent(min(limit, 500))


@storyteller_router.post(
    "/visitors/{visitor_id}/facts",
    name="storyteller:add_fact",
    dependencies=[Depends(current_admin_user)],
)
async def add_fact(
    visitor_id: str,
    body: dict[str, Any],
    store: Store = Depends(get_storyteller_store),
) -> dict[str, bool]:
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(422, "text is required")
    store.add_fact(visitor_id, text, body.get("weight", "normal"))
    return {"ok": True}


@storyteller_router.put(
    "/instructions/{scope}",
    name="storyteller:set_instruction",
    dependencies=[Depends(current_admin_user)],
)
async def set_instruction(
    scope: str,
    body: dict[str, Any],
    store: Store = Depends(get_storyteller_store),
) -> dict[str, bool]:
    store.set_instruction(scope, body.get("text", ""))
    return {"ok": True}
