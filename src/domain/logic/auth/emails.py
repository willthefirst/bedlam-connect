"""Auth-flow transactional emails — link construction + render + send.

Domain-layer wrapper around `src.framework.email.send_email`. Owns:

  - URL shape for verify / reset links (so the routes can move without
    the email module knowing about them — single source of truth for
    the link template).
  - Jinja rendering of `src/domain/templates/emails/*.{html,txt}`.

Hooks in `src.auth_config.UserManager` call these — never the
framework's `send_email` directly — so verify/reset link construction
stays in one place. Adding a new transactional email is a new function
here, not a hook-body rewrite.
"""

from __future__ import annotations

from src.domain.models import User
from src.framework.email import absolute_url, send_email
from src.framework.rendering.templating import templates


def _render(template_name: str, **context: object) -> str:
    """Render one of the email templates to a string. The Jinja env
    is the same one HTTP responses use — keeps autoescape behavior
    consistent (.html files autoescape, .txt files don't, by
    extension)."""
    template = templates.env.get_template(f"emails/{template_name}")
    return template.render(**context)


async def send_verification_email(user: User, token: str) -> None:
    """Send the verify-your-email message.

    `token` is fastapi-users' verification JWT. The link lands on
    `GET /auth/verify?token=...` (the page route in `auth_pages.py`),
    which renders a confirm-button page; the user's click POSTs to
    the sibling handler that actually consumes the token and signs
    them in. GET deliberately does NOT mutate — see
    `auth_pages.py:get_verify_page` for why (link prefetchers).
    """
    verify_url = absolute_url(f"/auth/verify?token={token}")
    context = {
        "username": user.username,
        "verify_url": verify_url,
    }
    await send_email(
        to=user.email,
        subject="Verify your Bedlam Connect email",
        html=_render("verify.html", **context),
        text=_render("verify.txt", **context),
    )


async def send_password_reset_email(user: User, token: str) -> None:
    """Send the password-reset email.

    `token` is the JWT minted by fastapi-users' reset router; it's
    consumed by `POST /auth/reset-password` (the same router) when
    the user submits the form on `/auth/reset-password/{token}`. Link
    shape must match the GET page route in `auth_pages.py`.
    """
    reset_url = absolute_url(f"/auth/reset-password/{token}")
    context = {
        "username": user.username,
        "reset_url": reset_url,
    }
    await send_email(
        to=user.email,
        subject="Reset your Bedlam Connect password",
        html=_render("reset_password.html", **context),
        text=_render("reset_password.txt", **context),
    )
