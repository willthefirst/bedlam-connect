"""Tests for `src/framework/config.py`."""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from .config import Settings


def test_environment_defaults_to_production():
    """ENVIRONMENT should default to production for safety.

    This prevents dev tools (like livereload) from accidentally loading
    in production if the ENVIRONMENT variable is not explicitly set.
    """
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings(SECRET="test", DATABASE_URL="postgresql://test")
        assert settings.ENVIRONMENT == "production"


def test_environment_can_be_set_to_development():
    """ENVIRONMENT can be explicitly set to development."""
    with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
        settings = Settings(
            SECRET="test",
            DATABASE_URL="postgresql://test",
            ENVIRONMENT="development",
        )
        assert settings.ENVIRONMENT == "development"


def test_observability_defaults_are_quota_safe():
    """Sample-rate defaults are pinned because a regression to `1.0`
    (the SDK's default) would silently 10× the Sentry bill on prod
    traffic. Replay defaults to off — it's a paid add-on."""
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings(SECRET="test", DATABASE_URL="postgresql://test")
        assert settings.SENTRY_DSN == ""
        assert settings.SENTRY_TRACES_SAMPLE_RATE == 0.1
        assert settings.SENTRY_PROFILES_SAMPLE_RATE == 0.1
        assert settings.SENTRY_REPLAY_SAMPLE_RATE == 0.0
        assert settings.SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE == 0.0
        assert settings.APP_RELEASE == ""


def test_storyteller_defaults_are_off_and_on_the_persisted_volume():
    """No secret → the hooks 503 until the deploy sets one (see
    `src/domain/routes/storyteller.py`); the store lands under `data/`,
    the volume prod persists across blue/green."""
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings(SECRET="test", DATABASE_URL="postgresql://test")
        assert settings.STORYTELLER_SECRET == ""
        assert settings.STORYTELLER_DB_PATH == "data/storyteller.db"
        # No site key → `base.html` renders no snippet at all; the default
        # endpoint is the same-origin path nginx proxies to the sidecar.
        assert settings.STORYTELLER_SITE_KEY == ""
        assert settings.STORYTELLER_ENDPOINT == "/storyteller"


@pytest.mark.parametrize(
    "value",
    [
        "www.bedlamconnect.com",  # the #1614 prod value
        "bedlamconnect.com/",
        "//bedlamconnect.com",
        "ftp://bedlamconnect.com",
        "https://",
    ],
)
def test_app_base_url_without_http_scheme_and_host_refuses_to_boot(value):
    """A scheme-less base renders email links as relative `href`s —
    Gmail silently repairs them, Resend's viewer and stricter clients
    resolve them against their own domain and 404 (#1614). Failing at
    boot turns a bad deploy secret into a failed health check."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValidationError, match="APP_BASE_URL must be an absolute"):
            Settings(
                SECRET="test", DATABASE_URL="postgresql://test", APP_BASE_URL=value
            )


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://www.bedlamconnect.com", "https://www.bedlamconnect.com"),
        ("https://www.bedlamconnect.com/", "https://www.bedlamconnect.com"),
        ("http://localhost:8000", "http://localhost:8000"),
    ],
)
def test_app_base_url_accepts_absolute_urls_and_strips_trailing_slash(value, expected):
    """Trailing slash is stripped here so link builders join with a
    single `/` — no `//auth/...` from a `.env` value ending in `/`."""
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings(
            SECRET="test", DATABASE_URL="postgresql://test", APP_BASE_URL=value
        )
        assert settings.APP_BASE_URL == expected


def test_app_base_url_default_is_valid():
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings(SECRET="test", DATABASE_URL="postgresql://test")
        assert settings.APP_BASE_URL == "http://localhost:8000"


def test_missing_required_field_reports_from_the_validation_error():
    """The friendly "missing variables" message names the fields the
    validation error reports as missing, not fields absent from
    `os.environ` but supplied another way (kwargs, `.env`)."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="- SECRET") as exc_info:
            Settings(DATABASE_URL="postgresql://test", _env_file=None)
        assert "DATABASE_URL" not in str(exc_info.value)
