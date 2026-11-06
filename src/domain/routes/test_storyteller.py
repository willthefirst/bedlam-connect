"""Tests for `/internal/storyteller/*` — the Storyteller consumer routes.

Pins the two auth schemes: the hooks accept only requests signed with
`STORYTELLER_SECRET` (503 when the app has none, 401 otherwise), and the
viewer + its data routes walk the admin ladder (anonymous → login,
non-admin → 403, admin → 200). Plus the protocol behaviours the service
relies on: the startup healthcheck story is acknowledged but not stored,
and an unknown visitor is a 404.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.storyteller.adapter import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    Store,
    sign,
)
from src.domain.models import User
from src.domain.routes.storyteller import get_storyteller_store
from src.framework.config import settings
from tests.helpers import promote_to_admin

pytestmark = pytest.mark.asyncio

SECRET = "test-storyteller-secret"


@pytest.fixture
def store(tmp_path, test_app: FastAPI) -> Store:
    """Point the routes at a store on a temp path (never `data/`)."""
    s = Store(tmp_path / "storyteller.db")
    test_app.dependency_overrides[get_storyteller_store] = lambda: s
    yield s
    test_app.dependency_overrides.pop(get_storyteller_store, None)


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setattr(settings, "STORYTELLER_SECRET", SECRET)
    return SECRET


def signed(body: bytes = b"", secret: str = SECRET) -> dict[str, str]:
    ts = str(int(time.time()))
    return {
        TIMESTAMP_HEADER: ts,
        SIGNATURE_HEADER: sign(secret, ts, body),
        "Content-Type": "application/json",
    }


def story(**overrides):
    s = {
        "schema_version": "1",
        "visit_id": "visit-1",
        "visitor_id": "visitor-1",
        "started_at": "2026-11-05T10:00:00",
        "outcome": {"label": "bounce", "confidence": 0.6},
        "narrative": "They looked at one post and left.",
        "tags": ["bounce"],
        "visitor_summary": "Probably a drive-by.",
        "trajectory": [],
    }
    s.update(overrides)
    return s


# ---- hooks ---------------------------------------------------------------


async def test_hooks_are_503_until_the_secret_is_configured(
    test_client: AsyncClient, store, monkeypatch
):
    monkeypatch.setattr(settings, "STORYTELLER_SECRET", "")
    body = json.dumps(story()).encode()
    r = await test_client.post(
        "/internal/storyteller/stories", content=body, headers=signed(body)
    )
    assert r.status_code == 503
    r = await test_client.get("/internal/storyteller/visitors/x", headers=signed())
    assert r.status_code == 503


async def test_unsigned_and_forged_hook_calls_are_401(
    test_client: AsyncClient, store, secret
):
    body = json.dumps(story()).encode()
    r = await test_client.post("/internal/storyteller/stories", content=body)
    assert r.status_code == 401
    r = await test_client.post(
        "/internal/storyteller/stories",
        content=body,
        headers=signed(body, secret="wrong"),
    )
    assert r.status_code == 401
    r = await test_client.get("/internal/storyteller/visitors/x")
    assert r.status_code == 401
    assert store.recent() == [], "nothing was stored"


async def test_signed_story_is_stored_and_readable_via_the_read_hook(
    test_client: AsyncClient, store: Store, secret
):
    body = json.dumps(story()).encode()
    r = await test_client.post(
        "/internal/storyteller/stories", content=body, headers=signed(body)
    )
    assert r.status_code == 200 and r.json() == {"ok": True}

    r = await test_client.get(
        "/internal/storyteller/visitors/visitor-1", headers=signed()
    )
    assert r.status_code == 200
    assert r.json()["summary"] == "Probably a drive-by."
    assert r.json()["schema_version"] == "1"


async def test_unknown_visitor_is_404(test_client: AsyncClient, store, secret):
    r = await test_client.get("/internal/storyteller/visitors/nobody", headers=signed())
    assert r.status_code == 404


async def test_startup_healthcheck_is_acknowledged_not_stored(
    test_client: AsyncClient, store: Store, secret
):
    body = json.dumps({"schema_version": "1", "healthcheck": True}).encode()
    r = await test_client.post(
        "/internal/storyteller/stories", content=body, headers=signed(body)
    )
    assert r.status_code == 200 and r.json() == {"ok": True, "healthcheck": True}
    assert store.recent() == []


# ---- viewer ---------------------------------------------------------------


async def test_anonymous_browser_is_sent_to_login(test_client: AsyncClient, store):
    r = await test_client.get(
        "/internal/storyteller/ui", headers={"accept": "text/html"}
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/auth/login?next=/internal/storyteller/ui"


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/internal/storyteller/ui"),
        ("GET", "/internal/storyteller/recent"),
        ("POST", "/internal/storyteller/visitors/v/facts"),
        ("PUT", "/internal/storyteller/instructions/global"),
    ],
)
async def test_non_superuser_gets_403_on_viewer_routes(
    authenticated_client: AsyncClient, store, method, path
):
    r = await authenticated_client.request(method, path, json={"text": "x"})
    assert r.status_code == 403


async def test_superuser_sees_the_viewer_and_its_data(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    store: Store,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    store.save_story(story())

    r = await authenticated_client.get("/internal/storyteller/ui")
    assert r.status_code == 200
    assert "<title>Storyteller</title>" in r.text
    # The page fetches its data from the prefix it was served under.
    assert 'const P = "/internal/storyteller";' in r.text
    assert "__PREFIX__" not in r.text

    r = await authenticated_client.get("/internal/storyteller/recent?limit=10")
    assert r.status_code == 200
    assert [s["visit_id"] for s in r.json()] == ["visit-1"]


async def test_superuser_can_teach_storyteller_about_a_visitor(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    store: Store,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)

    r = await authenticated_client.post(
        "/internal/storyteller/visitors/visitor-7/facts",
        json={"text": "A colleague testing the site", "weight": "high"},
    )
    assert r.status_code == 200
    r = await authenticated_client.post(
        "/internal/storyteller/visitors/visitor-7/facts", json={"text": "  "}
    )
    assert r.status_code == 422
    r = await authenticated_client.put(
        "/internal/storyteller/instructions/global", json={"text": "Be brief."}
    )
    assert r.status_code == 200

    memory = store.visitor("visitor-7")
    assert memory is not None
    assert [f["text"] for f in memory["facts"]] == ["A colleague testing the site"]
    assert memory["instructions"]["global"] == "Be brief."
