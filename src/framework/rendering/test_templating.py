"""Tests for `src/framework/rendering/templating.py`."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

from .templating import _env, days_ago, get_template_context, register_template_globals


def test_register_template_globals_updates_env():
    """`register_template_globals` is the only entrypoint domain code
    uses to wire entity-specific values into Jinja — verify it forwards
    kwargs to `_env.globals` directly so a renamed kwarg surfaces here
    instead of as a missing-variable render error."""
    sentinel = object()
    register_template_globals(__test_marker__=sentinel)
    assert _env.globals["__test_marker__"] is sentinel
    del _env.globals["__test_marker__"]


def test_framework_owns_no_domain_globals():
    """The framework env should expose only domain-agnostic globals at
    rest. Domain enums, per-kind schemas, and view helpers are
    registered from `src/domain/template_globals.py`; tests that exercise
    the framework env in isolation must explicitly load that module."""
    # `field_spec` is the only framework-declared global; everything
    # else either comes from domain registration or is a Jinja built-in.
    # A snapshot test would lock down too much, so just assert the
    # framework's own contribution survives.
    assert "field_spec" in _env.globals


def test_livereload_not_loaded_in_production():
    """Livereload should not be loaded when is_development is False."""
    with patch("src.framework.rendering.templating.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "production"
        context = get_template_context()
        assert context["is_development"] is False


def test_livereload_loaded_in_development():
    """Livereload should be loaded when is_development is True."""
    with patch("src.framework.rendering.templating.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "development"
        context = get_template_context()
        assert context["is_development"] is True


def test_observability_frontend_exposed_in_template_context():
    """`observability_frontend` is the dict `base.html` reads to render
    the browser SDK init block. The framework asks the abstraction for
    it; provider-specific shape is the backend's concern."""
    sentinel = {"provider": "sentry", "dsn": "https://abc@sentry.io/1"}
    with patch(
        "src.framework.rendering.templating.observability"
    ) as mock_observability:
        mock_observability.frontend_context.return_value = sentinel
        context = get_template_context()
    assert context["observability_frontend"] is sentinel


def test_observability_frontend_none_when_disabled():
    """`None` from the backend → `None` in the context. `base.html`
    treats `None` as "skip the browser SDK script tag entirely"."""
    with patch(
        "src.framework.rendering.templating.observability"
    ) as mock_observability:
        mock_observability.frontend_context.return_value = None
        context = get_template_context()
    assert context["observability_frontend"] is None


def test_storyteller_frontend_follows_the_site_key():
    """`storyteller_frontend` is `None` without a site key (no snippet) and
    `{endpoint, site_key}` with one — the dict `base.html` inits from."""
    with patch("src.framework.rendering.templating.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "production"
        mock_settings.STORYTELLER_SITE_KEY = ""
        mock_settings.STORYTELLER_ENDPOINT = "/storyteller"
        assert get_template_context()["storyteller_frontend"] is None

        mock_settings.STORYTELLER_SITE_KEY = "k"
        assert get_template_context()["storyteller_frontend"] == {
            "endpoint": "/storyteller",
            "site_key": "k",
        }


# --- days_ago ------------------------------------------------------------


def test_days_ago_today():
    assert days_ago(date.today()) == "today"


def test_days_ago_yesterday():
    assert days_ago(date.today() - timedelta(days=1)) == "1d ago"


def test_days_ago_a_few_days():
    assert days_ago(date.today() - timedelta(days=4)) == "4d ago"


def test_days_ago_under_30():
    assert days_ago(date.today() - timedelta(days=29)) == "29d ago"


def test_days_ago_months():
    assert days_ago(date.today() - timedelta(days=60)) == "2mo ago"


def test_days_ago_over_a_year():
    assert days_ago(date.today() - timedelta(days=400)) == "1y ago"


def test_days_ago_accepts_datetime():
    dt = datetime.combine(date.today() - timedelta(days=5), datetime.min.time())
    assert days_ago(dt) == "5d ago"


def test_days_ago_none_returns_empty_string():
    assert days_ago(None) == ""


def test_days_ago_filter_registered():
    """The filter must be registered in the Jinja env for templates to use it."""
    assert "days_ago" in _env.filters
