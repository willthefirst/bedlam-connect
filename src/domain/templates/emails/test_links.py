"""Every link in every transactional email is absolute.

Email bodies render outside the request scope, so a relative `href` has
no page to resolve against. Some clients (Gmail) silently repair it;
others (Resend's viewer, stricter clients) resolve it against their own
domain and 404 — which is how #1614 shipped unnoticed. This test renders
each email through its real domain sender with the real settings and
scans every `href`, so a relative link fails here whether it comes from
the base URL or from a hand-written `href="/..."` in a template.

`test_every_email_template_is_covered` keeps the list honest: a new
`emails/*.html` template without a case below fails the suite.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from selectolax.parser import HTMLParser

from src.domain.logic.auth.emails import (
    send_password_reset_email,
    send_verification_email,
)
from src.domain.logic.posts.emails import send_post_message_email

EMAILS_DIR = Path(__file__).resolve().parent
ABSOLUTE_HREF = re.compile(r"^(https?://[^/]+|mailto:)")
# Any token in a text part that carries an app path — the
# copy-into-your-browser link. Extend the alternation with new routes.
TEXT_APP_URL = re.compile(r"[^\s()<>]*/(?:auth|posts)/[^\s()<>]*")

_USER = SimpleNamespace(id=uuid.uuid4(), email="alice@example.com", username="alice")
_POST = SimpleNamespace(
    id=uuid.uuid4(),
    owner=SimpleNamespace(email="poster@example.com"),
    kind="program_intake",
    intake_detail=SimpleNamespace(program=SimpleNamespace(name="Sunrise Program")),
)

# template stem → (`send_email` to mock, coroutine that sends that email)
_AUTH = "src.domain.logic.auth.emails.send_email"
_POSTS = "src.domain.logic.posts.emails.send_email"
CASES = {
    "verify": (_AUTH, lambda: send_verification_email(_USER, token="tok")),
    "reset_password": (_AUTH, lambda: send_password_reset_email(_USER, token="tok")),
    "post_message": (
        _POSTS,
        lambda: send_post_message_email(post=_POST, sender=_USER, body="hi"),
    ),
}


async def _render(stem: str, monkeypatch) -> dict:
    target, send = CASES[stem]
    send_email_mock = AsyncMock()
    monkeypatch.setattr(target, send_email_mock)
    await send()
    return send_email_mock.call_args.kwargs


def test_every_email_template_is_covered():
    stems = {p.stem for p in EMAILS_DIR.glob("*.html")}
    assert stems == set(
        CASES
    ), "Add a case to CASES for each email template so its links are checked"


@pytest.mark.asyncio
@pytest.mark.parametrize("stem", sorted(CASES))
async def test_every_html_href_is_absolute(stem, monkeypatch):
    kwargs = await _render(stem, monkeypatch)

    hrefs = [
        a.attributes.get("href") or "" for a in HTMLParser(kwargs["html"]).css("a")
    ]
    assert hrefs, f"{stem}.html rendered no links"
    relative = [h for h in hrefs if not ABSOLUTE_HREF.match(h)]
    assert not relative, f"{stem}.html has non-absolute hrefs: {relative}"


@pytest.mark.asyncio
@pytest.mark.parametrize("stem", sorted(CASES))
async def test_every_text_url_is_absolute(stem, monkeypatch):
    """The text part has no `href`s to parse; check its bare app URLs
    instead (the copy-into-your-browser link)."""
    kwargs = await _render(stem, monkeypatch)

    urls = TEXT_APP_URL.findall(kwargs["text"])
    assert urls, f"{stem}.txt rendered no app URL"
    relative = [u for u in urls if not ABSOLUTE_HREF.match(u)]
    assert not relative, f"{stem}.txt has non-absolute URLs: {relative}"
