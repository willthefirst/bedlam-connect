"""Tests for `src/domain/logic/auth/emails.py`.

Pin the link shape + send-call contract. The framework's `send_email`
is mocked — these tests don't exercise the transport layer (covered
in `src/framework/email/test_sender.py`)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.logic.auth.emails import (
    send_password_reset_email,
    send_verification_email,
)


@pytest.mark.asyncio
async def test_send_password_reset_email_calls_send_email_with_user_email(monkeypatch):
    """The user's `email` is the recipient (not `username` — username
    is a display field; email is the wire-level identity for
    fastapi-users)."""
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.auth.emails.send_email", send_email_mock)

    user = SimpleNamespace(
        id=uuid.uuid4(),
        email="alice@example.com",
        username="alice",
    )
    await send_password_reset_email(user, token="abc.def.ghi")

    assert send_email_mock.call_count == 1
    kwargs = send_email_mock.call_args.kwargs
    assert kwargs["to"] == "alice@example.com"
    assert kwargs["subject"] == "Reset your Bedlam Connect password"


@pytest.mark.asyncio
async def test_send_password_reset_email_builds_absolute_url_with_token(monkeypatch):
    """The link in the email must be an absolute URL — `APP_BASE_URL`
    + the reset path + the token. Email clients can't resolve relative
    paths since they aren't running inside the request scope. The token
    is passed verbatim — fastapi-users' reset router consumes it via
    the path param, not a query string."""
    monkeypatch.setattr(
        "src.framework.email.links.settings.APP_BASE_URL",
        "https://app.example.com",
    )
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.auth.emails.send_email", send_email_mock)

    user = SimpleNamespace(email="alice@example.com", username="alice")
    await send_password_reset_email(user, token="my-token")

    kwargs = send_email_mock.call_args.kwargs
    expected_url = "https://app.example.com/auth/reset-password/my-token"
    assert expected_url in kwargs["text"]
    assert expected_url in kwargs["html"]


@pytest.mark.asyncio
async def test_send_password_reset_email_renders_username_in_body(monkeypatch):
    """The greeting line references the user's `username` — small
    personalization, also a tripwire for empty/null username if a
    future schema change loosens the field."""
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.auth.emails.send_email", send_email_mock)

    user = SimpleNamespace(email="alice@example.com", username="alice")
    await send_password_reset_email(user, token="t")

    kwargs = send_email_mock.call_args.kwargs
    assert "alice" in kwargs["text"]
    assert "alice" in kwargs["html"]


@pytest.mark.asyncio
async def test_send_password_reset_email_renders_both_parts(monkeypatch):
    """Both `html` and `text` are non-empty — the framework's
    `send_email` requires both, and the template pair must both
    exist."""
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.auth.emails.send_email", send_email_mock)

    user = SimpleNamespace(email="alice@example.com", username="alice")
    await send_password_reset_email(user, token="t")

    kwargs = send_email_mock.call_args.kwargs
    assert kwargs["html"].strip().startswith("<")
    assert "<" not in kwargs["text"]  # plain text only


# --- send_verification_email -------------------------------------------------


@pytest.mark.asyncio
async def test_send_verification_email_builds_query_param_link(monkeypatch):
    """Verify link is `GET /auth/verify?token=...` — query string,
    not path param (different from reset). The landing page route in
    `auth_pages.py:get_verify_page` reads the token via
    `request.query_params`."""
    monkeypatch.setattr(
        "src.framework.email.links.settings.APP_BASE_URL",
        "https://app.example.com",
    )
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.auth.emails.send_email", send_email_mock)

    user = SimpleNamespace(email="alice@example.com", username="alice")
    await send_verification_email(user, token="verify-tok")

    kwargs = send_email_mock.call_args.kwargs
    expected = "https://app.example.com/auth/verify?token=verify-tok"
    assert expected in kwargs["text"]
    assert expected in kwargs["html"]
    assert kwargs["subject"] == "Verify your Bedlam Connect email"
    assert kwargs["to"] == "alice@example.com"


@pytest.mark.asyncio
async def test_send_verification_email_renders_both_parts(monkeypatch):
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.auth.emails.send_email", send_email_mock)

    user = SimpleNamespace(email="alice@example.com", username="alice")
    await send_verification_email(user, token="t")

    kwargs = send_email_mock.call_args.kwargs
    assert kwargs["html"].strip().startswith("<")
    assert "<" not in kwargs["text"]
    assert "alice" in kwargs["text"]
