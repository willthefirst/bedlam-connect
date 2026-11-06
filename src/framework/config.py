from pathlib import Path
from urllib.parse import urlparse

from pydantic import ConfigDict, ValidationError, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET: str
    DATABASE_URL: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ENVIRONMENT: str = "production"
    # Seed-user email the dev-only auto-login route logs in as. Read
    # by `src.domain.routes.dev.dev_auth` when `ENVIRONMENT="development"`
    # — the route is not mounted in any other environment so this
    # value is inert in production. Defaults to the admin user
    # `seed.py` creates so a fresh `dev seed` + `dev up` lands the
    # developer (or the Playwright MCP agent) authenticated without
    # extra config.
    DEV_LOGIN_EMAIL: str = "admin@example.com"

    # Transactional email — see `src/framework/email/README.md` for the
    # backend dispatch rule. `console` is the safe default: no real
    # mail sent without an explicit env-var flip. `EMAIL_FROM` is read
    # by every backend (including `console`, which prints it). The
    # `APP_BASE_URL` is needed to build absolute links in emails
    # (verify, password reset) — relative paths don't work outside the
    # request scope. It must carry its scheme (`https://…`):
    # `_validate_app_base_url` refuses to boot otherwise, because a
    # scheme-less value renders as a relative `href` that some clients
    # silently repair and others resolve against their own domain.
    EMAIL_BACKEND: str = "console"
    EMAIL_FROM: str = "no-reply@bedlamconnect.com"
    APP_BASE_URL: str = "http://localhost:8000"
    RESEND_API_KEY: str | None = None

    # Error tracking + tracing. Read by `src/framework/observability/`,
    # which picks a backend (Sentry or Noop) based on `SENTRY_DSN`. Set
    # in production via the `.env` file on the droplet or as a CI/CD
    # secret. Empty DSN → the app runs with no provider at all.
    SENTRY_DSN: str = ""
    # Separate DSN for the browser SDK — points at the frontend Sentry
    # project so JS errors are triaged independently from backend errors.
    # Empty → no browser SDK loaded. Set via `SENTRY_BROWSER_DSN` env var.
    SENTRY_BROWSER_DSN: str = ""
    # Sample rates default to 10% so a traffic spike doesn't tank the
    # Sentry quota. Override per-environment if you need fuller traces.
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    SENTRY_PROFILES_SAMPLE_RATE: float = 0.1
    # Session Replay is opt-in (paid feature, larger payload). `0.0`
    # disables; bump the on-error rate to e.g. `1.0` to record replays
    # only when something throws.
    SENTRY_REPLAY_SAMPLE_RATE: float = 0.0
    SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE: float = 0.0
    # Release tag (typically the deploy's git SHA) used by both the
    # backend SDK and the browser SDK. Provider-agnostic name so a
    # future swap doesn't churn the deploy pipeline. Empty → no tag.
    APP_RELEASE: str = ""

    # Anti-bot defense for the public auth forms (register, forgot-
    # password) — see `src/framework/http/antibot.py`. The honeypot half
    # runs unconditionally (no key, no network); the Cloudflare Turnstile
    # challenge is gated on `CAPTCHA_ENABLED` so tests, local dev, and
    # programmatic contract clients pass without a real key. Set all three
    # in the prod `.env` to turn the challenge on. `TURNSTILE_SITE_KEY` is
    # public (embedded in the rendered HTML widget); `TURNSTILE_SECRET_KEY`
    # is server-side only (sent to Cloudflare's siteverify endpoint).
    CAPTCHA_ENABLED: bool = False
    TURNSTILE_SITE_KEY: str = ""
    TURNSTILE_SECRET_KEY: str = ""

    # Storyteller (visit stories) — see `src/domain/logic/storyteller/README.md`.
    # `STORYTELLER_SECRET` is the HMAC key the service signs its hook
    # requests with; the same value goes in the service's environment.
    # Empty → the hooks answer 503 (misconfigured, not forged). The DB path
    # is the SQLite file stories land in; `data/` is the persisted volume.
    STORYTELLER_SECRET: str = ""
    STORYTELLER_DB_PATH: str = "data/storyteller.db"

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("APP_BASE_URL")
    @classmethod
    def _validate_app_base_url(cls, value: str) -> str:
        """Require an absolute `http(s)://host` URL and strip any trailing
        slash, so link builders can join paths with a single `/`.

        Failing here (not at send time) is what turns a bad deploy
        secret into a failed `/health` check and a rollback, instead of
        a stream of broken emails."""
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                f"APP_BASE_URL must be an absolute http(s) URL, got {value!r}"
                f" — did you mean 'https://{value.lstrip('/')}'?"
            )
        return value.rstrip("/")

    def __init__(self, **kwargs):
        try:
            # Try to initialize normally - pydantic_settings will try .env file first, then environment variables
            super().__init__(**kwargs)
        except ValidationError as e:
            # If validation fails, provide helpful error message
            env_file = Path(".env")

            # Read missing fields off the error itself — probing
            # `os.getenv` would misreport fields supplied via `.env` or
            # kwargs and mask the real error (e.g. a bad APP_BASE_URL).
            missing_fields = [
                str(err["loc"][0]) for err in e.errors() if err["type"] == "missing"
            ]

            if missing_fields:
                fields_str = "\n".join(f"- {field}" for field in missing_fields)
                example_env = "\n".join(
                    f"{field}=your_{field.lower()}_here" for field in missing_fields
                )

                if not env_file.exists():
                    error_msg = (
                        f"\n\nError: Missing required environment variables!"
                        f"\nMissing variables: {fields_str}"
                        f"\n\nFor local development, create a .env file with:"
                        f"\n{example_env}"
                        f"\n\nFor production, set these as environment variables in Railway."
                    )
                else:
                    error_msg = (
                        f"\n\nError: Missing required environment variables!"
                        f"\nMissing variables: {fields_str}"
                        f"\n\nPlease add these to your .env file or set as environment variables."
                    )

                raise ValueError(error_msg) from e
            else:
                # Re-raise the original validation error if it's not about missing fields
                raise


settings = Settings()
