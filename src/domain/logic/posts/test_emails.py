"""Tests for `src/domain/logic/posts/emails.py`.

Pin the recipient / reply-to / link-shape contract for the post-message
email. The framework's `send_email` is mocked — these tests don't
exercise the transport layer (covered in
`src/framework/email/test_sender.py`)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.logic.posts.emails import send_post_message_email


def _post(owner_email: str = "poster@example.com", headline: str = "Sunrise Program"):
    """Minimal stand-in for a `Post` row — only the fields the email
    module reads. `SimpleNamespace` keeps the test off the DB.

    Shaped as a `program_intake` so the real `post_feed_headline`
    derives the subject line from the linked program's name — that value
    becomes the hyperlinked headline in the email."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner=SimpleNamespace(email=owner_email),
        kind="program_intake",
        intake_detail=SimpleNamespace(program=SimpleNamespace(name=headline)),
    )


def _sender(email: str = "sender@example.com", username: str = "sender"):
    return SimpleNamespace(id=uuid.uuid4(), email=email, username=username)


@pytest.mark.asyncio
async def test_recipient_is_post_owner_email(monkeypatch):
    """The recipient is the post's owner, not the sender — the whole
    point of the flow is to deliver a message to the poster."""
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.posts.emails.send_email", send_email_mock)

    await send_post_message_email(
        post=_post(owner_email="poster@example.com"),
        sender=_sender(),
        body="hello there",
    )

    kwargs = send_email_mock.call_args.kwargs
    assert kwargs["to"] == "poster@example.com"


@pytest.mark.asyncio
async def test_reply_to_is_sender_email(monkeypatch):
    """`Reply-To` carries the sender's email so the poster's "Reply"
    in their mail client goes back to the real human, not to
    `EMAIL_FROM` (the no-reply mailbox). This is the load-bearing
    behavior of the whole feature — the conversation continues
    off-platform."""
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.posts.emails.send_email", send_email_mock)

    await send_post_message_email(
        post=_post(),
        sender=_sender(email="alice@example.com"),
        body="hi",
    )

    assert send_email_mock.call_args.kwargs["reply_to"] == "alice@example.com"


@pytest.mark.asyncio
async def test_body_appears_in_both_parts(monkeypatch):
    """The user-supplied body lands verbatim in both the HTML and
    plain-text parts. Autoescape on the `.html` template handles HTML
    safety — the `.txt` template is plain text."""
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.posts.emails.send_email", send_email_mock)

    await send_post_message_email(
        post=_post(),
        sender=_sender(),
        body="I have a referral that matches",
    )

    kwargs = send_email_mock.call_args.kwargs
    assert "I have a referral that matches" in kwargs["text"]
    assert "I have a referral that matches" in kwargs["html"]


@pytest.mark.asyncio
async def test_body_is_html_escaped_in_html_part(monkeypatch):
    """The `.html` template autoescapes by extension — user-supplied
    body must not survive as raw HTML."""
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.posts.emails.send_email", send_email_mock)

    await send_post_message_email(
        post=_post(),
        sender=_sender(),
        body="<script>alert(1)</script>",
    )

    kwargs = send_email_mock.call_args.kwargs
    assert "<script>" not in kwargs["html"]
    assert "&lt;script&gt;" in kwargs["html"]


@pytest.mark.asyncio
async def test_email_includes_absolute_post_url(monkeypatch):
    """The post link (hyperlinked from the headline) must be absolute
    (`APP_BASE_URL` + `/posts/{id}`) — email clients can't resolve
    relative paths since they aren't running in the request scope."""
    monkeypatch.setattr(
        "src.framework.email.links.settings.APP_BASE_URL",
        "https://app.example.com",
    )
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.posts.emails.send_email", send_email_mock)

    post = _post()
    await send_post_message_email(post=post, sender=_sender(), body="hi")

    kwargs = send_email_mock.call_args.kwargs
    expected_url = f"https://app.example.com/posts/{post.id}"
    assert expected_url in kwargs["text"]
    assert expected_url in kwargs["html"]


@pytest.mark.asyncio
async def test_sender_username_surfaces_in_body(monkeypatch):
    """The sender's display name (`username`) names who's reaching out
    and who to reply to. The reply address itself lives only on the
    `Reply-To:` header, not in the body prose."""
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.posts.emails.send_email", send_email_mock)

    await send_post_message_email(
        post=_post(),
        sender=_sender(email="alice@example.com", username="alice"),
        body="hi",
    )

    kwargs = send_email_mock.call_args.kwargs
    assert "alice" in kwargs["text"]
    assert "alice" in kwargs["html"]
    assert "alice@example.com" not in kwargs["text"]
    assert "alice@example.com" not in kwargs["html"]


@pytest.mark.asyncio
async def test_post_headline_is_the_hyperlinked_subject(monkeypatch):
    """The post's derived headline (`post_feed_headline`) is the subject
    line and is hyperlinked to the post in the HTML part."""
    monkeypatch.setattr(
        "src.framework.email.links.settings.APP_BASE_URL",
        "https://app.example.com",
    )
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.posts.emails.send_email", send_email_mock)

    post = _post(headline="Sunrise Program")
    await send_post_message_email(post=post, sender=_sender(), body="hi")

    kwargs = send_email_mock.call_args.kwargs
    post_url = f"https://app.example.com/posts/{post.id}"
    assert "Sunrise Program" in kwargs["text"]
    assert f'<a href="{post_url}">Sunrise Program</a>' in kwargs["html"]


@pytest.mark.asyncio
async def test_renders_both_html_and_text_parts(monkeypatch):
    send_email_mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.posts.emails.send_email", send_email_mock)

    await send_post_message_email(post=_post(), sender=_sender(), body="hi")

    kwargs = send_email_mock.call_args.kwargs
    assert kwargs["html"].strip().startswith("<")
    assert "<html" in kwargs["html"]
    assert "<" not in kwargs["text"]
