from __future__ import annotations

from contextvars import ContextVar
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

if TYPE_CHECKING:
    from src.framework.access.actor.actor import Actor

from src.framework.config import settings
from src.framework.observability import observability
from src.framework.rendering.form_fields import field_spec
from src.framework.rendering.labels import (
    entity_create_label,
    entity_edit_label,
    entity_filter_label,
)
from src.framework.rendering.route_urls import (
    breadcrumb_entity_item,
    entity_form_url,
    entity_lock_reason,
    entity_url,
)

auto_reload = settings.ENVIRONMENT == "development"


def days_ago(value: datetime | date | None) -> str:
    """Compact relative age — '4d ago', '2mo ago', '1y ago', 'today'.

    Used by the home-page 'My active posts' widget and any compact row
    view that needs a terse timestamp rather than an absolute date.
    """
    if value is None:
        return ""
    d = value.date() if isinstance(value, datetime) else value
    delta = date.today() - d
    days = delta.days
    if days <= 0:
        return "today"
    if days == 1:
        return "1d ago"
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    return f"{days // 365}y ago"


def format_post_date(value: datetime | date | None) -> str:
    """Craigslist-style short date — `May 15` for current-year posts,
    `May 15, 2025` for older. Used by the posts list/detail templates so
    the same timestamp reads the same way in both places.

    `%-d` strips a leading zero from the day (`May 5`, not `May 05`).
    Linux/macOS only; this app runs on neither Windows nor any platform
    that needs `%#d`. If that changes, swap to `strftime('%b %d').lstrip('0')`.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        return ""
    today = date.today()
    if d.year == today.year:
        return d.strftime("%b %-d")
    return d.strftime("%b %-d, %Y")


_env = Environment(
    # Two search roots: framework owns `base.html`, `_shared/` macros, and
    # the generic `views/` chrome; domain owns per-entity templates. The
    # FileSystemLoader resolves names by walking the list, so domain
    # templates can `{% extends "views/list.html" %}` (resolved from
    # framework) and reference `{% from "_shared/..." %}` the same way.
    loader=FileSystemLoader(["src/framework/templates", "src/domain/templates"]),
    autoescape=select_autoescape(["html", "xml"]),
    auto_reload=auto_reload,
)

# Framework-owned globals: schema-driven form-field helper plus the
# canonical entity URL helpers (`entity_url` / `entity_form_url` — see
# `route_urls.py` and the `template_route_check.py` lint). Everything
# entity-specific — enums, per-kind create schemas, view helpers — is
# registered from `src/domain/template_globals.py`.
# `static_version` — appended to `/static/...?v=X` references so the
# `StaticLongCacheMiddleware` knows the URL is safe to cache for a
# year (deploys change the SHA → URLs change → caches bust). Empty
# string when `APP_RELEASE` is unset (local dev, smoke tests), which
# falls through to the short-TTL branch — no surprise long-caching of
# in-flight asset edits.
_env.globals["static_version"] = settings.APP_RELEASE
_env.globals["field_spec"] = field_spec
_env.globals["entity_url"] = entity_url
_env.globals["entity_form_url"] = entity_form_url
# `entity_lock_reason(name)` — REASON_* code if the current viewer fails the
# entity's read_policy (so a link to it should render as `locked_link`),
# else `None`. See `_shared/_locked.html` and `route_urls.entity_lock_reason`.
_env.globals["entity_lock_reason"] = entity_lock_reason
# `breadcrumb_entity_item(name)` — the (label, href, lock_reason) tuple
# every view-type template's collection-back segment renders. Centralizes
# the lock-aware lookup so no view-type template can ship without it.
# See `_shared/_breadcrumb.html` and `route_urls.breadcrumb_entity_item`.
_env.globals["breadcrumb_entity_item"] = breadcrumb_entity_item
# `entity_create_label(name, kind=None)` — the single source of truth for
# "Create X" strings across CTAs and form-page H1s. See
# `src/framework/rendering/labels.py`.
_env.globals["entity_create_label"] = entity_create_label
# `entity_edit_label(name, kind=None)` — the create-label twin for the
# edit-page H1 and any "Edit X" button text. See `labels.py`.
_env.globals["entity_edit_label"] = entity_edit_label
_env.globals["entity_filter_label"] = entity_filter_label
_env.filters["format_post_date"] = format_post_date
_env.filters["days_ago"] = days_ago

# Per-request viewer — pinned by `APIResponse.html_response` immediately
# before rendering so macros that can't reach template context (e.g.
# `viewer_is_admin`, `entity_link` via `entity_lock_reason`) consult the
# same identity the route's `current_user_dep` resolved. Handlers don't
# call `set_viewer` directly; the central html_response wrapper does.
_viewer_var: ContextVar[Actor | None] = ContextVar("_viewer", default=None)


def set_viewer(user: Actor | None) -> None:
    """Pin the per-task viewer for the upcoming render.

    Called by `APIResponse.html_response` before every template render,
    so macros that can't access template context (`viewer_is_admin`,
    `entity_link` via `entity_lock_reason`) see the same identity the
    route resolved. Test fixtures still call this directly to drive
    `viewer_is_admin` in isolation."""
    _viewer_var.set(user)


def viewer_is_admin() -> bool:
    """Return True when the current viewer is a superuser.

    Registered as the ``viewer_is_admin`` template global so macros can
    check admin capability without receiving it as an explicit argument.
    """
    u = _viewer_var.get()
    return u is not None and bool(getattr(u, "is_superuser", False))


_env.globals["viewer_is_admin"] = viewer_is_admin


def turnstile_site_key() -> str:
    """Return the Cloudflare Turnstile site key to embed in the anti-bot
    widget, or "" when the challenge is disabled.

    Registered as the ``turnstile_site_key`` template global so the
    ``_shared/antibot.html`` macro can render the widget without the key
    being threaded through every form's render context. Empty string
    (challenge off) makes the macro skip the widget + script entirely —
    the honeypot half still renders. See `src/framework/http/antibot.py`.
    """
    return settings.TURNSTILE_SITE_KEY if settings.CAPTCHA_ENABLED else ""


_env.globals["turnstile_site_key"] = turnstile_site_key


def register_template_globals(**kwargs: Any) -> None:
    """Add Jinja globals to the framework's environment.

    Called from `src/domain/template_globals.py` at app load to expose
    domain enums, per-kind create schemas, and view helpers to templates.
    The framework deliberately knows nothing about what gets registered;
    the call site is the domain.
    """
    _env.globals.update(kwargs)


templates = Jinja2Templates(env=_env)


# Add global template variables for development features
def get_template_context():
    """Get global template context.

    `observability_frontend` is the provider-agnostic dict consumed by
    `base.html` to render the browser SDK init block — `None` when no
    provider is configured (no script tag rendered). See
    `src/framework/observability/` for the contract and how to add a new
    provider.

    `storyteller_frontend` is the same shape of switch for the Storyteller
    recording snippet: `{endpoint, site_key}` when `STORYTELLER_SITE_KEY`
    is set, else `None` (no script tag). See
    `src/domain/logic/storyteller/README.md`.
    """
    return {
        "is_development": settings.ENVIRONMENT == "development",
        "livereload_port": "35729",
        "observability_frontend": observability.frontend_context(),
        "storyteller_frontend": (
            {
                "endpoint": settings.STORYTELLER_ENDPOINT,
                "site_key": settings.STORYTELLER_SITE_KEY,
            }
            if settings.STORYTELLER_SITE_KEY
            else None
        ),
    }
