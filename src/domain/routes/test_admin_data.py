"""Tests for `/admin/data/` — the admin's Datasette, behind
`current_admin_user`.

Pins the auth ladder (anonymous → login, non-admin → 403, admin → the
Datasette page), that saved queries are served from the app DB, and the
end-to-end write: the "Add a note" form posts through the route (CSRF
token intact) and the note is stamped with the signed-in admin as its
author.
"""

import re
import sqlite3

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.admin_data.datasette_app import (
    build_datasette,
    get_admin_data_app,
)
from src.domain.models import User
from tests.helpers import migrate_sqlite_file, promote_to_admin

pytestmark = pytest.mark.asyncio


@pytest.fixture
def admin_data_db(tmp_path, test_app: FastAPI):
    """Point the route at a Datasette over a migrated temp-file DB. The
    default test DB is in-memory and has no observability views."""
    path = tmp_path / "admin_data.db"
    migrate_sqlite_file(path)
    # One instance for the whole test, like production's cached app.
    app = build_datasette(str(path)).app()
    test_app.dependency_overrides[get_admin_data_app] = lambda: app
    yield path
    test_app.dependency_overrides.pop(get_admin_data_app, None)


async def test_anonymous_browser_is_sent_to_login(test_client: AsyncClient):
    response = await test_client.get("/admin/data/", headers={"accept": "text/html"})
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?next=/admin/data/"


async def test_non_superuser_gets_403(authenticated_client: AsyncClient):
    response = await authenticated_client.get("/admin/data/")
    assert response.status_code == 403


async def test_superuser_sees_the_saved_queries(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    admin_data_db,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)

    response = await authenticated_client.get("/admin/data/bedlam")
    assert response.status_code == 200
    assert "1. New connections" in response.text
    assert "5. Add a note" in response.text

    response = await authenticated_client.get(
        "/admin/data/bedlam/new_connections.json?_shape=array"
    )
    assert response.status_code == 200
    assert response.json() == []


async def test_ad_hoc_sql_cannot_write(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    admin_data_db,
):
    """Datasette's read connections are `mode=ro`: arbitrary SQL from the
    query box can read but never modify the app DB."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)

    response = await authenticated_client.get(
        "/admin/data/bedlam.json",
        params={"sql": "delete from posts", "_shape": "array"},
    )
    assert response.status_code >= 400


async def test_add_note_form_writes_a_note_authored_by_the_admin(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    admin_data_db,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)

    form = await authenticated_client.get("/admin/data/bedlam/add_note")
    assert form.status_code == 200
    token = re.search(r'name="csrftoken" value="([^"]+)"', form.text).group(1)
    # Datasette's CSRF check pairs the form token with its `ds_csrftoken`
    # cookie. A browser sends both; the fixture pins a fixed Cookie
    # header, so add Datasette's cookie to it by hand.
    csrf_cookie = form.cookies["ds_csrftoken"]
    session_cookie = authenticated_client.headers["Cookie"]

    subject_id = "0" * 32
    response = await authenticated_client.post(
        "/admin/data/bedlam/add_note",
        headers={"Cookie": f"{session_cookie}; ds_csrftoken={csrf_cookie}"},
        data={
            "csrftoken": token,
            "subject_type": "post",
            "subject_id": subject_id,
            "action": "reviewed",
            "value": "",
            "note": "Looked fine",
        },
    )
    assert response.status_code in (200, 302), response.text[:500]

    with sqlite3.connect(admin_data_db) as conn:
        rows = conn.execute(
            "select subject_type, subject_id, action, note, author_id from admin_notes"
        ).fetchall()
    assert rows == [
        ("post", subject_id, "reviewed", "Looked fine", logged_in_user.id.hex)
    ]
