"""Pins the `lifespan` scheduler-gating contract: DISABLE_SCHEDULER=1 skips
the subsystem entirely (no construction, no registration, no start), while
the default path constructs + registers + starts. The contract matters
because APScheduler's `add_job` logs "Adding job tentatively…" whenever a
job is registered against a not-yet-started scheduler — calling
`register_jobs` on a disabled scheduler is observable noise.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import User
from src.main import lifespan
from tests.helpers import make_clinician_with_org

pytestmark = pytest.mark.asyncio


# --- Landing: `/` is the bare-domain entry, split by auth state --------
#
# "Home" now means the referral board, unfiltered
# (`/posts?kind=referral`). `/` is the single home entry point: a
# signed-in viewer hitting `/` is redirected there. An anonymous visitor gets
# the public landing page (`landing.html`) rendered in place — never the login
# wall, and never `/posts` (which is auth-gated). `/home` is retired from
# the live flow but kept defined (see `read_home`).


async def test_root_redirects_authed_to_referral_board(
    authenticated_client: AsyncClient,
):
    """A signed-in viewer hitting `/` is redirected to the referral board,
    with no default filters (`/posts?kind=referral`) — the signed-in
    "home"."""
    response = await authenticated_client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/posts?kind=referral"


async def test_root_anonymous_renders_public_landing(test_client: AsyncClient):
    """An anonymous visitor hitting `/` gets the public landing page in
    place (200 HTML) — not a redirect to the login wall, and not the
    auth-gated `/posts`."""
    response = await test_client.get(
        "/", headers={"Accept": "text/html"}, follow_redirects=False
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Welcome to Bedlam Connect" in response.text


async def test_authenticated_home_renders_quicklinks(
    authenticated_client: AsyncClient,
):
    """An authenticated viewer hitting `/home` gets the goal hub — NOT a
    redirect. It renders the intent CTAs as three columns of plain links
    (Refer a patient / Find your next client / Manage), and (because a
    fresh account can't post yet) surfaces the dynamic `#home-setup` task
    at the top."""
    response = await authenticated_client.get("/home", follow_redirects=False)
    assert response.status_code == 200
    body = response.text
    for href in (
        # Refer a patient
        "/posts/form?kind=referral",
        "/posts?kind=clinician_opening",
        # Find your next client
        "/posts/form?kind=clinician_opening",
        "/posts?kind=referral",
        # Manage
        "/posts?owner=me",
        "/clinicians?owner=me",
        "/users/me",
    ):
        assert f'href="{href}"' in body, f"home goal hub missing a link to {href}"
    # A fresh account isn't post-ready, so the setup task is surfaced.
    assert 'id="home-setup"' in body, "setup task must show when the viewer can't post"
    # No network access yet → the greeting is "Welcome.", not "Welcome back."
    assert (
        HTMLParser(body).css_first("h1").text(strip=True) == "Welcome."
    ), "teased viewer must be greeted with Welcome."


async def test_authenticated_home_greets_returning_provider(
    superuser_client: AsyncClient,
):
    """A viewer with network access (`can_act_as_provider`, here via the
    superuser grant) is greeted with the returning-provider header."""
    response = await superuser_client.get("/home", follow_redirects=False)
    assert response.status_code == 200
    assert HTMLParser(response.text).css_first("h1").text(strip=True) == "Welcome back."


async def test_authenticated_home_hides_setup_task_when_post_ready(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The dynamic `#home-setup` task disappears once the viewer can post —
    here, a verified email plus a verified clinician profile (Claim A)."""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = await session.get(User, logged_in_user.id)
            user.is_verified = True
            session.add(
                make_clinician_with_org(
                    owner_id=logged_in_user.id, clinician_verified=True
                )
            )

    response = await authenticated_client.get("/home", follow_redirects=False)
    assert response.status_code == 200
    assert (
        'id="home-setup"' not in response.text
    ), "setup task must be hidden once the viewer can post"


async def test_anonymous_home_renders_public_landing(
    test_client: AsyncClient,
):
    """An anonymous visitor hitting `/home` gets the public landing page
    (not the login wall) — the goal hub is signed-in only, so anonymous
    falls through to `landing.html`."""
    response = await test_client.get(
        "/home",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "/auth/login" not in response.headers.get("location", "")


# --- lifespan -----------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_skips_scheduler_entirely_when_disabled(monkeypatch):
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")

    with (
        patch("src.main.check_database_health", new=AsyncMock()),
        patch("src.main.make_scheduler") as mk,
        patch("src.main.register_jobs") as reg,
    ):
        async with lifespan(FastAPI()):
            pass

        mk.assert_not_called()
        reg.assert_not_called()


# --- 401 handling: one login URL, three client shapes ------------------
#
# `unauthorized_exception_handler` turns a 401 (typically an expired
# session hitting an auth-gated route's `current_active_user` dependency)
# into a login redirect for browsers while leaving JSON APIs untouched.
# `POST /posts` is auth-gated; the 401 fires at the dependency *before*
# the body is parsed, so an empty unauthenticated POST exercises the
# handler for every client shape below.


async def test_expired_session_htmx_submit_redirects_via_hx_header(
    test_client: AsyncClient,
):
    """An HTMX form submit with no session gets `204` + `HX-Redirect` — NOT
    the raw `{"detail": ...}` JSON, which `hx-target-4xx` would otherwise
    swap into the form. htmx sends `Accept: */*`, so the redirect has to
    key off the `HX-Request` header, not the Accept sniff."""
    response = await test_client.post(
        "/posts",
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 204
    assert response.headers["HX-Redirect"] == "/auth/login?next=/posts"
    # No body — nothing for the response-targets extension to render.
    assert response.text == ""


async def test_expired_session_browser_nav_gets_302(test_client: AsyncClient):
    """A full-page browser navigation (`Accept: text/html`, no `HX-Request`)
    still gets the classic `302` to the login wall."""
    response = await test_client.post(
        "/posts",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?next=/posts"


async def test_expired_session_api_client_gets_json_401(test_client: AsyncClient):
    """A JSON API client (no `HX-Request`, no `text/html`) keeps the
    machine-readable `401` body — the redirect arms are browser-only."""
    response = await test_client.post(
        "/posts",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.asyncio
async def test_lifespan_starts_scheduler_when_enabled(monkeypatch):
    monkeypatch.delenv("DISABLE_SCHEDULER", raising=False)
    scheduler = MagicMock()

    with (
        patch("src.main.check_database_health", new=AsyncMock()),
        patch("src.main.make_scheduler", return_value=scheduler) as mk,
        patch("src.main.register_jobs") as reg,
    ):
        async with lifespan(FastAPI()):
            pass

        mk.assert_called_once()
        reg.assert_called_once_with(scheduler)
        scheduler.start.assert_called_once()
        scheduler.shutdown.assert_called_once_with(wait=False)
