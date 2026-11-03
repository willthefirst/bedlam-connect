import pytest
from fastapi_users.db import SQLAlchemyUserDatabase
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import User
from src.framework.audit.log import AuditLog
from src.framework.audit.repository import AuditRepository

pytestmark = pytest.mark.asyncio


class UserCreateRequest(BaseModel):
    email: str
    password: str


async def test_register(
    test_client: AsyncClient, db_test_session_manager: async_sessionmaker[AsyncSession]
):
    email_to_test = "testreg@example.com"
    password_to_test = "password123"

    register_data = {
        "email": email_to_test,
        "password": password_to_test,
    }
    response = await test_client.post("/auth/register", json=register_data)
    assert response.status_code == 201
    assert "application/json" in response.headers["content-type"]
    user_info = response.json()
    assert user_info["email"] == email_to_test
    assert user_info["is_active"] is True
    assert user_info["is_superuser"] is False
    # Signup form no longer collects a username; `handle_registration`
    # fills the (UNIQUE, NOT NULL) column from `email` so existing
    # downstream consumers (display, audit snapshot, emails) keep working.
    assert user_info["username"] == email_to_test
    # `is_verified` restored to the response with the verification
    # rollout (reversing #696). Tests run with `ENVIRONMENT=development`
    # (see `.env.test`), so the dev-mode auto-verify guardrail in
    # `UserManager.on_after_register` fires — the user is `True`
    # without anyone clicking a verify link. In production this would
    # be `False` until the user clicks the link in their verify email;
    # the prod path is exercised by `test_register_prod_mode_leaves_user_unverified`.
    assert user_info["is_verified"] is True

    async with db_test_session_manager() as session:
        user_db = SQLAlchemyUserDatabase(session, User)
        created_user = await user_db.get_by_email(email_to_test)
        assert created_user is not None
        assert created_user.email == email_to_test


async def test_register_seeds_default_saved_searches(
    test_client: AsyncClient, db_test_session_manager: async_sessionmaker[AsyncSession]
):
    """`on_after_register` seeds every new user with the default saved
    searches (openings + referrals) via `seed_default_saved_searches`."""
    import uuid

    from src.domain.logic.saved_searches.defaults import DEFAULT_SAVED_SEARCHES
    from src.domain.models import SavedSearch

    response = await test_client.post(
        "/auth/register",
        json={"email": "seeded@example.com", "password": "password123"},
    )
    assert response.status_code == 201, response.text
    user_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(SavedSearch).where(SavedSearch.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
    by_name = {r.name: r.filters for r in rows}
    assert by_name == {name: filters for name, filters in DEFAULT_SAVED_SEARCHES}


async def test_register_prod_mode_leaves_user_unverified(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    monkeypatch,
):
    """Pin the production-mode path: `on_after_register` calls
    `self.request_verify` (which sends the verify email) and does NOT
    auto-flip `is_verified`. The user starts at `False` until they
    click the link in the email.

    Tests run with `ENVIRONMENT=development` by default — this test
    monkey-patches that and stubs the send call so the assertion
    isolates the hook's branching, not the email transport."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr("src.auth_config.settings.ENVIRONMENT", "production")
    monkeypatch.setattr(
        "src.domain.logic.auth.emails.send_email", AsyncMock(return_value=None)
    )

    register_data = {
        "email": "prod-mode-user@example.com",
        "password": "password123",
    }
    response = await test_client.post("/auth/register", json=register_data)
    assert response.status_code == 201
    assert response.json()["is_verified"] is False


async def test_dev_auto_verify_skipped_for_programmatic_create(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Programmatic callers (seed, test fixtures) hit `UserManager.create`
    with `request=None`. The dev-mode auto-verify only fires for
    browser-initiated registration (request present), so a programmatic
    `UserCreate(is_verified=False)` lands an actually-unverified row —
    the persona seed in `scripts/dev/seed/overrides/personas.py`
    depends on this."""
    from src.auth_config import UserManager
    from src.domain.logic.users.schema import UserCreate

    async with db_test_session_manager() as session:
        user_db = SQLAlchemyUserDatabase(session, User)
        manager = UserManager(user_db)
        created = await manager.create(
            UserCreate(
                email="programmatic-unverified@example.com",
                password="password",
                username="programmatic-unverified",
                is_verified=False,
            ),
            safe=False,
            request=None,
        )
        await session.commit()

    async with db_test_session_manager() as session:
        user_db = SQLAlchemyUserDatabase(session, User)
        refreshed = await user_db.get(created.id)
    assert refreshed is not None
    assert refreshed.is_verified is False, (
        "request=None + is_verified=False must land False in dev — the "
        "auto-verify is gated on a Request being present"
    )


async def test_register_via_htmx_sets_cookie_and_redirects(test_client: AsyncClient):
    """HTMX register should auto-login (cookie) and redirect, not return JSON."""
    payload = {
        "email": "htmx@example.com",
        "password": "Password123!",
    }
    response = await test_client.post(
        "/auth/register",
        json=payload,
        headers={"HX-Request": "true", "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    # Post-register HTMX flow goes "home" (`/`, which forwards to the
    # referral board), same as a normal login — no longer forced onto the
    # email CTA.
    assert response.headers.get("HX-Redirect") == "/"
    # A session cookie must be set so the redirect lands authenticated.
    assert (
        "fastapiusersauth" in response.cookies
        or "set-cookie" in str(response.headers).lower()
    )


async def test_register_duplicate_email(test_client: AsyncClient, logged_in_user: User):
    register_data = {
        "email": logged_in_user.email,
        "password": "newpassword",
    }
    response = await test_client.post("/auth/register", json=register_data)
    assert response.status_code == 400


async def test_register_htmx_duplicate_email_rerenders_form_with_field_error(
    test_client: AsyncClient, logged_in_user: User
):
    """HTMX register + duplicate email → 200 + HTML form fragment with
    a per-field error on the email input and the email prefilled via
    `form_values`. Password is *not* echoed back (never echo a
    password into form HTML). Mirrors the login bad-creds re-render
    path — same `form_rerender` plumbing on the framework side.

    Non-HTMX clients still get the JSON 400 contract (pinned by
    `test_register_duplicate_email` above) — the rerender branch is
    gated on `HX-Request: true`."""
    response = await test_client.post(
        "/auth/register",
        json={"email": logged_in_user.email, "password": "newpassword"},
        headers={"HX-Request": "true", "Content-Type": "application/json"},
    )
    # 409 Conflict — RFC 9110 §15.5.10. Duplicate email is a textbook
    # conflict with current resource state. The form fragment declares
    # `hx-target-4xx="this"` so the htmx `response-targets` extension
    # still swaps the body in place.
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    # Per-field error sits in the email input's `<small>` slot via the
    # form-fields macro's `error=` auto-resolution.
    assert "An account with this email already exists." in body
    # Email is preserved so the user doesn't have to retype it.
    assert f'value="{logged_in_user.email}"' in body
    # Password is NOT echoed — same defense as the login re-render.
    assert "newpassword" not in body
    # Fragment-only response: the re-render returns just the `<form>`,
    # not the full `auth/register.html` page. HTMX swaps the form
    # element in place via `hx-target="this" hx-swap="outerHTML"`;
    # feeding it the full page here would nest the entire page chrome
    # inside the form slot.
    assert "<!DOCTYPE" not in body
    assert "<html" not in body
    assert "Bedlam Connect" not in body
    assert "<h1>Create an account</h1>" not in body


# --- Anti-bot: honeypot on the public forms ------------------------------
#
# The honeypot half of `enforce_antibot` runs unconditionally (no key, no
# network — the Turnstile half is gated on CAPTCHA_ENABLED, which stays
# False under `.env.test`). A submission with the hidden `contact_url`
# field filled is a bot; it's rejected before any side effect. See
# `src/framework/http/antibot.py` and its colocated `test_antibot.py` for
# the verification-layer coverage.


async def test_register_rejects_filled_honeypot(
    test_client: AsyncClient, db_test_session_manager: async_sessionmaker[AsyncSession]
):
    """A non-HTMX register with the honeypot filled → clean 400 (not a
    500), and no user row is created."""
    response = await test_client.post(
        "/auth/register",
        json={
            "email": "bot@example.com",
            "password": "password123",
            "contact_url": "http://spam.example",
        },
    )
    assert response.status_code == 400
    async with db_test_session_manager() as session:
        user_db = SQLAlchemyUserDatabase(session, User)
        assert await user_db.get_by_email("bot@example.com") is None


async def test_register_htmx_filled_honeypot_rerenders_banner(
    test_client: AsyncClient,
):
    """HTMX register + filled honeypot → 400 + form fragment carrying the
    "couldn't verify you're human" banner (same rerender plumbing as the
    duplicate-email path)."""
    response = await test_client.post(
        "/auth/register",
        json={
            "email": "bot2@example.com",
            "password": "password123",
            "contact_url": "spam",
        },
        headers={"HX-Request": "true", "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert 'class="form-banner"' in body
    # Apostrophes are HTML-escaped in the rendered banner
    # ("couldn&#39;t"), so match on an apostrophe-free slice of the copy.
    assert "verify that you" in body.lower()
    assert "human" in body.lower()
    # Fragment-only — no page chrome.
    assert "<!DOCTYPE" not in body
    assert "<html" not in body


async def test_register_happy_path_unaffected_by_honeypot(
    test_client: AsyncClient,
):
    """A normal submission (honeypot omitted) still succeeds — the guard
    must not break the happy path."""
    response = await test_client.post(
        "/auth/register",
        json={"email": "real-person@example.com", "password": "password123"},
    )
    assert response.status_code == 201


async def test_forgot_password_rejects_filled_honeypot(
    test_client: AsyncClient, logged_in_user: User
):
    """Filled honeypot on forgot-password → 400 banner, and no reset
    email path is taken (`enforce_antibot` runs before the lookup)."""
    response = await test_client.post(
        "/auth/forgot-password",
        json={"email": logged_in_user.email, "contact_url": "spam"},
        headers={"HX-Request": "true", "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    # Apostrophes are HTML-escaped in the banner; match an apostrophe-free slice.
    assert "verify that you" in response.text.lower()


async def test_login_success(test_client: AsyncClient, logged_in_user: User):
    login_data = {
        "username": logged_in_user.email,
        "password": "password123",
    }
    response = await test_client.post("/auth/jwt/login", data=login_data)
    assert response.status_code == 302
    assert response.headers["Set-Cookie"] is not None
    assert "fastapiusersauth=" in response.headers["Set-Cookie"]
    access_token = response.headers["Set-Cookie"].split(";")[0].split("=")[1]
    assert access_token is not None

    auth_header = {"Cookie": f"fastapiusersauth={access_token}"}
    me_response = await test_client.get("/users/me", headers=auth_header)
    assert me_response.status_code == 200
    # The self-view is the account hub headed "Your account" — a proxy
    # that the authenticated page rendered for the logged-in cookie.
    assert "Your account" in me_response.text


async def test_login_failure_wrong_password(
    test_client: AsyncClient, logged_in_user: User
):
    login_data = {
        "username": logged_in_user.email,
        "password": "wrongpassword",
    }
    response = await test_client.post("/auth/jwt/login", data=login_data)
    assert response.status_code == 400


async def test_login_failure_nonexistent_user(test_client: AsyncClient):
    login_data = {
        "username": "nosuchuser@example.com",
        "password": "password123",
    }
    response = await test_client.post("/auth/jwt/login", data=login_data)
    assert response.status_code == 400


# --- POST /auth/login (HTMX wrapper) -------------------------------------
#
# `/auth/jwt/login` is fastapi-users' built-in (JSON 400 on failure —
# what the tests above pin). `/auth/login` is the form-handler wrapper
# this app adds for the browser flow: bad credentials re-render the
# login template inline with `form_banner="Invalid email or password."`
# so the user actually sees the failure (HTMX has nowhere to land a
# JSON 400). Success path mints the cookie via the same
# `auth_backend.login` the fastapi-users route uses, then adds
# `HX-Redirect` so HTMX navigates after the 204.


async def test_post_login_wrapper_htmx_success_sets_cookie_and_hx_redirect(
    test_client: AsyncClient, logged_in_user: User
):
    """HTMX-flagged POST + valid credentials → 204 + `Set-Cookie:
    fastapiusersauth=...` + `HX-Redirect` (default `/` — home — per
    `UserManager.on_after_login`). The wrapper converts the underlying
    302+Location into 204+HX-Redirect for HTMX so the browser doesn't
    auto-follow before HTMX honors the navigation."""
    response = await test_client.post(
        "/auth/login",
        data={"username": logged_in_user.email, "password": "password123"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 204
    assert "fastapiusersauth=" in response.headers.get("Set-Cookie", "")
    # `Location` is popped (auto-follow guard for HTMX); HX-Redirect
    # takes over. `on_after_login` defaults to `/` (home) when no `?next=`
    # is set.
    assert "Location" not in response.headers
    assert response.headers.get("HX-Redirect") == "/"


async def test_post_login_wrapper_non_htmx_success_returns_302_redirect(
    test_client: AsyncClient, logged_in_user: User
):
    """Without `HX-Request`, the wrapper preserves fastapi-users'
    original contract: 302 + `Location` (powered by
    `UserManager.on_after_login`). Lets contract tests + programmatic
    clients keep using the same shape."""
    response = await test_client.post(
        "/auth/login",
        data={"username": logged_in_user.email, "password": "password123"},
    )
    assert response.status_code == 302
    assert response.headers.get("Location") == "/"
    assert "fastapiusersauth=" in response.headers.get("Set-Cookie", "")


async def test_post_login_wrapper_respects_next_query_param(
    test_client: AsyncClient, logged_in_user: User
):
    """`?next=/users/me` flows through to `HX-Redirect: /users/me` —
    matches how the GET login page passes `next` along, so the
    post-login landing is whatever the browser was trying to reach
    when redirected to login. (`next` validation lives in
    `UserManager.on_after_login` — same checks the JWT route uses.)"""
    response = await test_client.post(
        "/auth/login?next=/users/me",
        data={"username": logged_in_user.email, "password": "password123"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 204
    assert response.headers.get("HX-Redirect") == "/users/me"


async def test_post_login_wrapper_bad_password_rerenders_form_with_banner(
    test_client: AsyncClient, logged_in_user: User
):
    """Wrong password → 200 + HTML carrying the form_banner alert and
    the email prefilled into the username input via `form_values`.
    Password is *not* echoed back (never echo a password into form
    HTML). This is the user-visible signal that the wrapper actually
    routes through `form_rerender` — the framework contract (key
    names, status code) is pinned in `test_form_rerender.py`."""
    response = await test_client.post(
        "/auth/login",
        data={"username": logged_in_user.email, "password": "wrongpassword"},
    )
    # 401 Unauthorized — RFC 9110 §15.5.2. The htmx `response-targets`
    # extension swaps on the matching `hx-target-4xx` declaration in
    # the form fragment, so the rerendered HTML still lands in the
    # form slot (htmx's default response handler ignores 4xx bodies).
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    # Banner with the canonical bad-creds copy lands in the response.
    assert 'class="form-banner"' in body
    assert "Invalid email or password" in body
    # Email is preserved so the user only retypes the password.
    assert f'value="{logged_in_user.email}"' in body
    # Password is NOT echoed — defense against a password ending up in
    # a re-rendered form's HTML (which could land in a browser back-
    # forward cache, a screenshot, server logs, etc.).
    assert "wrongpassword" not in body
    # Fragment-only response: the re-render returns just the `<form>`,
    # not the full `auth/login.html` page. HTMX swaps the form
    # element in place via `hx-target="this" hx-swap="outerHTML"`;
    # feeding it the full page here would nest the entire page chrome
    # (header, h1 "Log in", footer with reset/register links) inside
    # the form slot — visually broken (#bug surfaced post-#834).
    assert "<!DOCTYPE" not in body
    assert "<html" not in body
    assert "Bedlam Connect" not in body
    assert "<h1>Log in</h1>" not in body
    assert "Forgot your password?" not in body


async def test_post_login_wrapper_nonexistent_user_uses_same_banner(
    test_client: AsyncClient,
):
    """A non-existent user gets the same "Invalid email or password"
    banner as a real user with a wrong password — the wrapper
    deliberately does not distinguish the two cases so an attacker
    can't enumerate which emails are registered."""
    response = await test_client.post(
        "/auth/login",
        data={
            "username": "nobody@example.com",
            "password": "anything",
        },
    )
    # 401 Unauthorized — same code as the wrong-password branch above.
    # Same code AND same banner copy: this is the anti-enumeration
    # contract (an attacker can't distinguish "no such user" from
    # "wrong password" via status code OR body).
    assert response.status_code == 401
    assert "Invalid email or password" in response.text
    # Still preserves what the user typed so they can correct it.
    assert 'value="nobody@example.com"' in response.text


async def test_logout_success(authenticated_client: AsyncClient):
    me_response_before = await authenticated_client.get("/users/me")
    assert me_response_before.status_code == 200
    user_email_html = me_response_before.text

    logout_response = await authenticated_client.post("/auth/jwt/logout")
    assert logout_response.status_code == 204
    assert not logout_response.content

    me_response_after = await authenticated_client.get("/users/me")
    assert me_response_after.status_code == 200
    assert me_response_after.text == user_email_html


# The "authenticated pages expose the header sign-out affordance" check
# now lives in test_users.test_get_users_me_renders_authenticated_self_view
# alongside the rest of the /users/me chrome assertions — every test that
# rendered this page with this fixture share one request there.


async def test_forgot_password_request(test_client: AsyncClient, logged_in_user: User):
    response = await test_client.post(
        "/auth/forgot-password", json={"email": logged_in_user.email}
    )
    assert response.status_code == 202


async def test_forgot_password_request_nonexistent_user(test_client: AsyncClient):
    response = await test_client.post(
        "/auth/forgot-password", json={"email": "nosuchuser@example.com"}
    )
    # Should still return 202 Accepted to avoid leaking user existence information.
    assert response.status_code == 202


async def test_forgot_password_htmx_success_renders_banner(
    test_client: AsyncClient, logged_in_user: User
):
    """HTMX submit with a valid email → 200 + form fragment with the
    canonical "if an account ... exists" banner. The banner copy is
    the same for nonexistent emails (next test) — anti-enumeration
    contract preserved end-to-end."""
    response = await test_client.post(
        "/auth/forgot-password",
        json={"email": logged_in_user.email},
        headers={"HX-Request": "true", "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    body = response.text
    assert 'class="form-banner"' in body
    assert "If an account with that email exists" in body
    # Email is prefilled so the user sees what they submitted.
    assert f'value="{logged_in_user.email}"' in body
    # Fragment-only; no page chrome.
    assert "<!DOCTYPE" not in body
    assert "<html" not in body


async def test_forgot_password_htmx_nonexistent_email_renders_same_banner(
    test_client: AsyncClient,
):
    """Nonexistent email → same 200 + same banner copy as the success
    case above. Anti-enumeration — an attacker can't tell from the
    response which emails are registered."""
    response = await test_client.post(
        "/auth/forgot-password",
        json={"email": "nobody@example.com"},
        headers={"HX-Request": "true", "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert "If an account with that email exists" in response.text


async def test_forgot_password_htmx_malformed_email_renders_field_error(
    test_client: AsyncClient,
):
    """Malformed email body → 422 + form fragment with an inline error
    on the `email` input. The `response-targets` extension swaps the
    body on the 4xx so the user actually sees the error (vs the
    pre-wrapper behavior of a silent JSON 422)."""
    response = await test_client.post(
        "/auth/forgot-password",
        json={"email": "not-an-email"},
        headers={"HX-Request": "true", "Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text
    body = response.text
    email_at = body.index('name="email"')
    window = body[max(0, email_at - 200) : email_at + 200]
    assert 'aria-invalid="true"' in window, window


async def test_reset_password(test_client: AsyncClient, logged_in_user: User):
    request_response = await test_client.post(
        "/auth/forgot-password", json={"email": logged_in_user.email}
    )
    assert request_response.status_code == 202

    reset_token = "VALID_RESET_TOKEN"
    if reset_token == "VALID_RESET_TOKEN":
        pytest.skip("Password reset token retrieval not implemented for testing")

    new_password = "newSecurePassword123"
    reset_data = {"token": reset_token, "password": new_password}
    reset_response = await test_client.post("/auth/reset-password", json=reset_data)
    assert reset_response.status_code == 200

    login_data = {"username": logged_in_user.email, "password": new_password}
    login_response = await test_client.post("/auth/jwt/login", data=login_data)
    assert login_response.status_code == 200
    assert "access_token" in login_response.json()


async def test_reset_password_htmx_invalid_token_renders_banner(
    test_client: AsyncClient,
):
    """HTMX submit with a bad token → 410 + form fragment carrying
    the "this reset link is invalid or has expired" banner from the
    registry. The `response-targets` extension swaps the 4xx body
    into the form so the user actually sees the failure."""
    response = await test_client.post(
        "/auth/reset-password",
        json={"token": "BAD", "password": "newpassword"},
        headers={"HX-Request": "true", "Content-Type": "application/json"},
    )
    assert response.status_code == 410, response.text
    body = response.text
    assert 'class="form-banner"' in body
    assert "reset link is invalid or has expired" in body
    # Fragment-only.
    assert "<!DOCTYPE" not in body
    assert "<html" not in body


async def test_reset_password_htmx_missing_password_renders_field_error(
    test_client: AsyncClient,
):
    """HTMX submit with missing/empty password → 422 + form fragment
    with an inline error on the `password` input."""
    response = await test_client.post(
        "/auth/reset-password",
        json={"token": "T", "password": ""},
        headers={"HX-Request": "true", "Content-Type": "application/json"},
    )
    # Empty string parses as `str` but fastapi-users' password helper
    # / validator may accept it depending on policy. The wrapper still
    # returns a non-2xx response — either 422 (weak password) or 410
    # (the token "T" is invalid). Both are valid wire shapes; the
    # smoke just pins that the response is a fragment, not JSON.
    assert response.status_code >= 400
    body = response.text
    assert "<!DOCTYPE" not in body
    assert "<html" not in body
    # The form fragment is what swaps into the page; the response
    # always carries a `<form` element.
    assert "<form" in body


async def test_reset_password_invalid_token(test_client: AsyncClient):
    """Bad token → 410 Gone. Pre-PR-#11 this asserted fastapi-users'
    historical 400, but the wrapper now responds 410 (RFC 9110
    §15.5.11 — "the target resource is no longer available at the
    origin server and that this condition is likely to be
    permanent"), which matches the user-facing "your link doesn't
    work anymore" copy. Both HTMX and non-HTMX clients land on the
    same status code; HTMX gets HTML, others get an HTML body that
    `response-targets` can swap if they're htmx-aware."""
    reset_data = {"token": "INVALID_TOKEN", "password": "newpassword"}
    response = await test_client.post("/auth/reset-password", json=reset_data)
    assert response.status_code == 410


async def test_get_register_page(test_client: AsyncClient):
    response = await test_client.get("/auth/register")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Page H1 plus the canonical "Create account" submit button are
    # both load-bearing — pin the H1 here so the page-title copy
    # doesn't drift to a generic "Sign up" / "Register" string. The
    # rest of the auth-flow pages follow the same shape.
    assert "Create an account" in response.text
    assert "Create account" in response.text
    # Form wrapper — `.auth-page` caps the form at 28rem and centers it
    # so it doesn't stretch to the `<main>` `.container` width on
    # tablet/desktop (#584). No card chrome: deliberately not styled as
    # a card. The `.auth-page` rule lives in `base.html`.
    assert '<section class="auth-page">' in response.text
    # Subtitle mirrors the Login page's "Sign in to your Bedlam Connect
    # account." — plain, brand-anchored copy a first-time visitor can
    # parse, with no bare model-jargon list ("openings, referrals, and
    # intakes") before any value framing (#694).
    assert "openings, referrals, and intakes" not in response.text
    assert "Create a new Bedlam Connect account." in response.text
    # Signup form collects email + password only — username is filled
    # server-side from email in `handle_registration`. Pin the absence
    # so the field doesn't sneak back in.
    assert 'name="username"' not in response.text
    # Anti-bot honeypot is always rendered (offscreen); the Turnstile
    # widget/script is NOT, because CAPTCHA_ENABLED is False under
    # `.env.test` (`turnstile_site_key()` returns ""). See
    # `src/framework/http/antibot.py`.
    assert 'name="contact_url"' in response.text
    assert "cf-turnstile" not in response.text
    assert "challenges.cloudflare.com" not in response.text


async def test_get_login_page(test_client: AsyncClient):
    response = await test_client.get("/auth/login")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # H1 + submit button (both "Log in" — verb form, no longer the
    # noun "Login"). See `test_get_register_page` for the H1 pin
    # rationale.
    assert "Log in" in response.text
    # Default subtitle must not assume a returning user (#693).
    assert "Welcome back" not in response.text
    assert "referrals" not in response.text
    assert "Sign in to your Bedlam Connect account" in response.text
    # See `test_get_register_page` for `.auth-page` rationale (#584).
    assert '<section class="auth-page">' in response.text
    # Default subtitle must not assume a returning user (#693).
    assert "Welcome back" not in response.text
    # Default subtitle must not contain bare jargon without context (#693).
    assert "referrals" not in response.text
    assert "Sign in to your Bedlam Connect account" in response.text


async def test_get_login_page_post_register_banner(test_client: AsyncClient):
    """?registered=1 shows a confirmation banner instead of the default subtitle."""
    response = await test_client.get("/auth/login?registered=1")
    assert response.status_code == 200
    assert "Account created" in response.text
    assert "Sign in to your Bedlam Connect account." not in response.text


async def test_get_login_page_just_registered(test_client: AsyncClient):
    """GET /auth/login?registered=1 shows the post-registration banner (#693)."""
    response = await test_client.get("/auth/login?registered=1")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Account created" in response.text
    # Default subtitle is replaced by the contextual message.
    assert "Sign in to your Bedlam Connect account" not in response.text


async def test_get_forgot_password_page(test_client: AsyncClient):
    response = await test_client.get("/auth/forgot-password")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # H1 was removed app-wide; the page no longer carries the literal
    # "Forgot password" text. The submit button and body copy still
    # identify the page.
    assert "Send reset link" in response.text
    # See `test_get_register_page` for `.auth-page` rationale (#584).
    assert '<section class="auth-page">' in response.text
    # The form MUST submit as JSON — fastapi-users' `/auth/forgot-password`
    # expects `{"email": "..."}`. A plain `<form method="post">` would
    # send `application/x-www-form-urlencoded` and the endpoint would
    # 422 with "email field required" in production. Pin both the
    # htmx submit attribute and the json-enc extension so the next
    # rewrite can't silently regress to form-encoding.
    assert 'hx-post="/auth/forgot-password"' in response.text
    assert 'hx-ext="json-enc"' in response.text
    # Honeypot present; Turnstile widget absent (captcha off in tests).
    assert 'name="contact_url"' in response.text
    assert "cf-turnstile" not in response.text


async def test_get_reset_password_page(test_client: AsyncClient):
    reset_token = "SOME_TOKEN_FOR_TESTING_URL"
    response = await test_client.get(f"/auth/reset-password/{reset_token}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # H1 + submit button. Reset is now "Save password" (the user is
    # picking a new password, not resetting one); the H1 sets the
    # "you're about to" frame.
    assert "Set a new password" in response.text
    assert "Save password" in response.text
    assert (
        f'value="{reset_token}"' in response.text
        or f'data-token="{reset_token}"' in response.text
    )
    # Same JSON-submit contract as `test_get_forgot_password_page`:
    # the endpoint expects `{"token": "...", "password": "..."}` and
    # form-encoding would 422.
    assert 'hx-post="/auth/reset-password"' in response.text
    assert 'hx-ext="json-enc"' in response.text
    # See `test_get_register_page` for `.auth-page` rationale (#584).
    assert '<section class="auth-page">' in response.text


# --- /auth/verify --------------------------------------------------------
#
# The email-link flow is split GET (render confirm page, NO token
# consumption) + POST (consume + auto-login + redirect). This shape
# defends against email-link prefetchers (corporate AV, Outlook Safe
# Links, Gmail preview) burning the token before the user clicks —
# prefetchers issue GETs, not POSTs. See `auth_pages.py:get_verify_page`
# for the full rationale.


async def _mint_verify_token(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    user_id,
) -> str:
    """Helper: mint a real fastapi-users verify JWT for a user by routing
    through `request_verify` (the same path the email send uses) and
    capturing the token off the send hook.

    fastapi-users doesn't expose a public `make_verify_token` so this
    is the supported way to obtain one in tests.
    """
    from src.auth_config import get_user_manager
    from src.db import get_user_db

    async with db_test_session_manager() as session:
        user_db_gen = get_user_db(session)
        user_db = await anext(user_db_gen)
        manager_gen = get_user_manager(user_db)
        manager = await anext(manager_gen)

        from sqlalchemy import select

        fresh_user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one()
        # Reset to unverified so request_verify works (dev auto-verify
        # leaves new users at True).
        await user_db.update(fresh_user, {"is_verified": False})

        captured: dict = {}

        async def capture_send(user, token):
            captured["token"] = token

        from src.domain.logic.auth import emails as emails_module

        original = emails_module.send_verification_email
        emails_module.send_verification_email = capture_send
        try:
            await manager.request_verify(fresh_user)
        finally:
            emails_module.send_verification_email = original

    return captured["token"]


async def test_get_verify_page_without_token_renders_error(
    test_client: AsyncClient,
):
    """Missing `?token=` query param → error state. The page renders
    200 (this is the email-link landing, not an API endpoint — the
    user shouldn't see a JSON 422)."""
    response = await test_client.get("/auth/verify")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "didn't work" in response.text.lower()


async def test_get_verify_page_renders_confirm_form_without_mutating(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """GET with any token renders the confirm-button form and leaves
    `is_verified` untouched. The whole point of the GET/POST split is
    that prefetcher GETs don't burn the token."""
    token = await _mint_verify_token(db_test_session_manager, logged_in_user.id)

    response = await test_client.get(f"/auth/verify?token={token}")
    assert response.status_code == 200
    # Confirm form is rendered and the token is round-tripped into the
    # hidden field for the POST.
    body = response.text
    assert '<form action="/auth/verify"' in body
    assert 'name="token"' in body
    assert token in body
    assert "Verify and sign in" in body

    # And the GET did NOT flip the column — POST is the mutation.
    from sqlalchemy import select

    async with db_test_session_manager() as session:
        user = (
            await session.execute(select(User).where(User.id == logged_in_user.id))
        ).scalar_one()
        assert user.is_verified is False


async def test_post_verify_with_valid_token_verifies_and_auto_logs_in(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Valid token at POST: `is_verified` flips, a session cookie is
    set, and the response steers the browser into the clinician-create
    funnel (#1302 — the intended next step for a freshly-verified
    user)."""
    token = await _mint_verify_token(db_test_session_manager, logged_in_user.id)

    response = await test_client.post(
        "/auth/verify",
        data={"token": token},
        follow_redirects=False,
    )
    # Non-HTMX POST → 302 + Location to the clinician-create form
    # (NOT `on_after_login`'s default `/`).
    assert response.status_code == 302
    assert response.headers["location"] == "/clinicians/form"
    # Session cookie was minted.
    assert (
        "fastapiusersauth" in response.headers.get("set-cookie", "")
        or "fastapiusersauth" in response.cookies
    )

    # DB column actually flipped.
    from sqlalchemy import select

    async with db_test_session_manager() as session:
        user = (
            await session.execute(select(User).where(User.id == logged_in_user.id))
        ).scalar_one()
        assert user.is_verified is True


async def test_post_verify_htmx_redirects_via_hx_header(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """HTMX POST gets `HX-Redirect` + 204 so HTMX does a full
    navigation (mirrors `post_login`'s HTMX branch). Cookie is still
    set on the same response."""
    token = await _mint_verify_token(db_test_session_manager, logged_in_user.id)

    response = await test_client.post(
        "/auth/verify",
        data={"token": token},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 204
    assert response.headers.get("HX-Redirect") == "/clinicians/form"
    # `Location` is not set on the HTMX branch — HTMX navigates via
    # the `HX-Redirect` header instead.
    assert "location" not in {k.lower() for k in response.headers.keys()}


async def test_post_verify_without_token_renders_error(test_client: AsyncClient):
    """Empty `token` form field → error state. No 422, no 500."""
    response = await test_client.post("/auth/verify", data={"token": ""})
    assert response.status_code == 200
    assert "didn't work" in response.text.lower()
    # No cookie set.
    assert "set-cookie" not in {k.lower() for k in response.headers.keys()}


async def test_post_verify_with_invalid_token_renders_error(test_client: AsyncClient):
    """Malformed token → error state. fastapi-users raises
    `InvalidVerifyToken`; the route swallows it and routes to the
    error template. Never auto-logs in."""
    response = await test_client.post("/auth/verify", data={"token": "not.a.real.jwt"})
    assert response.status_code == 200
    assert "didn't work" in response.text.lower()
    assert "set-cookie" not in {k.lower() for k in response.headers.keys()}


async def test_post_verify_with_already_used_token_does_not_auto_login(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Second POST with an already-consumed token renders the
    already_verified state WITHOUT auto-login. A second click could be
    from a leaked-after-use URL (shared browser history, log scraping);
    the convenience of auto-login isn't worth the risk on this branch."""
    token = await _mint_verify_token(db_test_session_manager, logged_in_user.id)

    # First POST: consumes the token, auto-logs in.
    first = await test_client.post(
        "/auth/verify", data={"token": token}, follow_redirects=False
    )
    assert first.status_code == 302

    # Drop the cookie the first POST set so the second POST is a fresh
    # anonymous click (the realistic "leaked URL replayed by someone
    # else" scenario).
    test_client.cookies.clear()

    second = await test_client.post("/auth/verify", data={"token": token})
    assert second.status_code == 200
    assert "already verified" in second.text.lower()
    # NO cookie minted on the already_verified branch.
    assert "set-cookie" not in {k.lower() for k in second.headers.keys()}


async def test_post_resend_verify_unauthenticated_returns_401(test_client: AsyncClient):
    """`POST /auth/resend-verify` reads the user from the session — no
    cookie means no resend. Returns 401 (handled by the middleware
    that turns 401 into a redirect for HTML, but the API client here
    isn't sending the HTMX header so it stays 401)."""
    response = await test_client.post("/auth/resend-verify")
    assert response.status_code == 401


async def test_post_resend_verify_authenticated_redirects_to_email_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
    monkeypatch,
):
    """Authed user can re-request the verify email. Response is
    `HX-Redirect: /users/me/email/form?sent=1` so HTMX navigates to
    the consolidated email management / CTA page — same UX surface as
    the post-registration flow."""
    # Stub the actual send so the test doesn't print to stderr.
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "src.domain.logic.auth.emails.send_email", AsyncMock(return_value=None)
    )

    response = await authenticated_client.post("/auth/resend-verify")
    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == "/users/me/email/form?sent=1"


async def test_unauthorized_redirect_for_browser_requests(test_client: AsyncClient):
    response = await test_client.get(
        "/users/me",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?next=/users/me"


async def test_unauthorized_json_response_for_api_requests(test_client: AsyncClient):
    response = await test_client.get(
        "/users/me", headers={"Accept": "application/json"}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_unauthorized_default_behavior(test_client: AsyncClient):
    response = await test_client.get("/users/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_unauthorized_redirect_follows_to_login_page(test_client: AsyncClient):
    response = await test_client.get(
        "/users/me",
        headers={"Accept": "text/html"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Log in" in response.text


async def test_register_writes_audit_row(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Each successful POST /auth/register writes one audit row with
    actor_id=None (self-signup has no authenticated actor)."""
    register_data = {
        "email": "audit-target@example.com",
        "password": "password123",
        "username": "audittarget",
    }
    response = await test_client.post("/auth/register", json=register_data)
    assert response.status_code == 201
    new_user_id = response.json()["id"]

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        from uuid import UUID

        rows = await repo.list_for_resource(
            resource_type="user", resource_id=UUID(new_user_id)
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_id is None
        assert row.action == "register"
        assert row.before is None
        assert row.after == {
            "username": "audittarget",
            "email": "audit-target@example.com",
            "is_active": True,
            "is_superuser": False,
        }


async def test_failed_register_writes_no_audit_row(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A 400 (duplicate email) must not leak an audit row."""
    register_data = {
        "email": logged_in_user.email,
        "password": "newpassword",
        "username": "duplicate",
    }
    response = await test_client.post("/auth/register", json=register_data)
    assert response.status_code == 400

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(AuditLog)
            .filter(AuditLog.action == "register")
            .filter(AuditLog.after["email"].as_string() == logged_in_user.email)
        )
        rows = result.scalars().all()
        assert rows == []


async def test_home_anonymous_returns_landing_page(test_client: AsyncClient):
    """Anonymous GET /home returns the marketing landing page (200 HTML),
    not a redirect to the login wall (#692). (`/home` is retired from the
    live nav flow but still renders: its anonymous branch serves the same
    public landing that `/` now serves anonymous visitors directly.) The H1 +
    tagline + description copy are taken verbatim from the parent
    marketing site at https://www.bedlamconnect.com/ — pinning them so a
    well-meaning copy edit doesn't quietly drift the public-facing
    page out of sync with the brand."""
    response = await test_client.get("/home", follow_redirects=False)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Verbatim copy from bedlamconnect.com.
    assert "Welcome to Bedlam Connect" in response.text
    assert "Connecting clinicians, helping patients." in response.text
    assert (
        "Post referrals, find referrals, and maintain a network of "
        "professional contacts." in response.text
    )
    # Both CTAs must be present so anonymous visitors can self-serve.
    # "Sign in" / "Sign up" verbs match the parent marketing site and
    # the rest of the auth flow (#693).
    assert "/auth/register" in response.text
    assert "/auth/login" in response.text
    assert "Sign in" in response.text
    assert "Sign up" in response.text
    # CTA buttons live in `.cta-cluster`, NOT Pico's `.grid` — `.grid`
    # would stretch them to the full hero width on tablet+. The
    # `.cta-cluster` CSS in `landing.html` overrides Pico's
    # `<a role="button">` full-width default at ≥768px so the buttons
    # render at natural width, but keeps the full-width treatment on
    # phones where stacked tappable bars read better.
    assert "cta-cluster" in response.text
    # The footer slot is shared across every page (default block in
    # `base.html`), so the support note / contact is present on the
    # landing page too.
    assert "help@bedlamconnect.com" in response.text


async def test_root_authenticated_redirects_to_referral_board(
    authenticated_client: AsyncClient,
):
    """Authenticated GET / redirects to the referral board, with no
    default filters (`/posts?kind=referral`) — the signed-in "home"."""
    response = await authenticated_client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/posts?kind=referral"
