import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.auth_config import (
    auth_backend,
    current_optional_user,
    fastapi_users,
)
from src.db import check_database_health
from src.domain import routes  # noqa: F401  # populates entity_registry
from src.domain import template_globals  # noqa: F401  # populates Jinja env globals
from src.domain.logic.users.schema import UserRead
from src.domain.logic.users.view import onboarding_readiness
from src.domain.routes import (
    access,
    admin,
    storyteller,
    user_email,
    verifications,
)
from src.domain.routes.auth import auth_pages, auth_routes
from src.domain.routes.dev import dev_auth, dev_components
from src.framework.config import settings
from src.framework.dispatch.registry import entity_registry
from src.framework.http.middleware import (
    StaticLongCacheMiddleware,
    StaticNoCacheMiddleware,
    StripEmptyQueryParamsMiddleware,
)
from src.framework.http.responses import APIResponse
from src.framework.http.static_files import MinifyingStaticFiles
from src.framework.observability import observability
from src.jobs.scheduler import make_scheduler, register_jobs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class _HealthAccessFilter(logging.Filter):
    """Drop uvicorn access log lines for the /health probe."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return "GET /health " not in message


logging.getLogger("uvicorn.access").addFilter(_HealthAccessFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os

    try:
        # CLINICIAN_TEST_MODE manages tables separately, so skip the check.
        skip_table_check = os.getenv("CLINICIAN_TEST_MODE") == "true"
        await check_database_health(skip_table_check=skip_table_check)
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        logger.error("Application startup aborted due to database issues")
        raise

    # APScheduler runs inside the app process so jobs share the real
    # async_session_maker and audit repository (see src/jobs/README.md).
    # DISABLE_SCHEDULER=1 skips the subsystem entirely (dev + pytest); job
    # registration is exercised by src/jobs/test_scheduler.py instead.
    if os.getenv("DISABLE_SCHEDULER") == "1":
        scheduler = None
    else:
        scheduler = make_scheduler()
        register_jobs(scheduler)
        scheduler.start()
        logger.info("APScheduler started")

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(title="Bedlam Connect", lifespan=lifespan)

# Initialize the error tracking / tracing provider. No-op when no DSN
# is configured — see `src/framework/observability/` for the contract
# and how to swap providers.
observability.init_app(app)

# Strip empty query-string pairs at request entry so HTML-form
# submissions ("Apply" with no filter selected → `?x=`) behave the same
# as omitting the param. See `src/framework/http/middleware.py` for the
# full convention rationale.
app.add_middleware(StripEmptyQueryParamsMiddleware)

if settings.ENVIRONMENT == "development":
    app.add_middleware(StaticNoCacheMiddleware)
else:
    # Production / staging — emit far-future cache headers on versioned
    # asset URLs and a short revalidating TTL on the rest. See the
    # middleware docstring for the URL convention.
    app.add_middleware(StaticLongCacheMiddleware)
    # Compress HTML + CSS + JSON over the wire. `minimum_size=500`
    # skips tiny responses where the gzip header itself would bloat
    # the payload. Same content + smaller transfer = lower TTFB on
    # every page, especially first-paint CSS (Lighthouse:
    # "render-blocking" insight). Dev is skipped — the LiveReload
    # snippet relies on bare HTTP/1.1 chunked frames.
    from starlette.middleware.gzip import GZipMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=500)


@app.exception_handler(HTTPException)
async def unauthorized_exception_handler(request: Request, exc: HTTPException):
    """Send 401s to /auth/login for browsers; pass JSON 401s through to APIs.

    Three client shapes, three responses — all landing on the same login
    URL so the fix is uniform across every auth-gated surface:

    - HTMX form submit (expired session mid-submit): htmx sends
      `Accept: */*`, so the `text/html` sniff below misses it. Without
      this branch it fell through to the JSON arm and the raw
      `{"detail": ...}` body got swapped into the form by `hx-target-4xx`.
      We detect the `HX-Request` header and answer `204` + `HX-Redirect`
      instead — htmx honors that header regardless of status and does a
      full-page navigation to login (no body to swap; matches the
      `deleted_response` idiom in `framework/http/responses.py`).
    - Full-page browser navigation (`Accept: text/html`): a plain `302`.
    - API client (JSON): the original `{"detail": ...}` body, unchanged.

    `next=<path>` round-trips the caller back after they re-auth.
    """
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        login_url = f"/auth/login?next={request.url.path}"
        if request.headers.get("HX-Request") == "true":
            return Response(status_code=204, headers={"HX-Redirect": login_url})
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(url=login_url, status_code=302)

    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/")
async def read_root(request: Request, user=Depends(current_optional_user)):
    # `/` is the one bare-domain entry AND the single source of truth for
    # "home". Every home affordance — the nav brand, the breadcrumb "Home"
    # root, the post-login / post-register redirects — points at `/`; this
    # handler is the only place that decides where home actually goes. So
    # changing the signed-in landing (destination or default filter) is a
    # one-line edit here, not a hunt across redirects and templates.
    #
    # Signed in → the posts board, unfiltered (no default kind or state —
    # the viewer picks their own filters).
    # Anonymous → the public landing page rendered in place (not the login
    # wall, and not `/posts`, which is auth-gated). `/home` is retired from
    # the live flow — nothing links to it — but kept defined below for
    # possible later use.
    if user is not None:
        return RedirectResponse(url="/posts", status_code=302)
    return APIResponse.html_response(
        template_name="landing.html",
        context={},
        request=request,
    )


@app.get("/home")
async def read_home(request: Request, user=Depends(current_optional_user)):
    # `/home` is the signed-in launchpad — a goal-oriented hub linking to
    # the app's main surfaces, rendered from `home.html`. Anonymous
    # visitors get the public landing page instead (not the login wall).
    #
    # Retired from the live flow: nothing in the app links here anymore
    # ("home" now means the referral board — see `read_root`). Kept
    # defined so the hub can be re-promoted later without rebuilding it.
    if user is not None:
        # `readiness` drives the dynamic "finish setting up" task at the
        # top of the hub: when the account can't post yet, the next
        # verification step is surfaced as the highest-priority action.
        return APIResponse.html_response(
            template_name="home.html",
            context={"readiness": onboarding_readiness(user)},
            request=request,
            current_user=user,
        )
    return APIResponse.html_response(
        template_name="landing.html",
        context={},
        request=request,
    )


app.include_router(
    fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"]
)

app.include_router(
    auth_routes.auth_api_router,
    prefix="/auth",
    tags=["auth"],
)

# `auth_pages` is included BEFORE `get_reset_password_router()` because
# the latter mounts a `POST /auth/forgot-password` at the same path as
# our HTMX-friendly wrapper. FastAPI matches in registration order, so
# whichever router is included first wins. The fastapi-users routes
# remain mounted (for any path the wrapper doesn't intercept) — see
# `auth_pages.post_forgot_password` for why we wrap.
app.include_router(auth_pages.auth_pages_api_router)
app.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(verifications.verifications_api_router)
app.include_router(access.access_router)
app.include_router(user_email.user_email_router)
app.include_router(admin.admin_router)
app.include_router(storyteller.storyteller_router)

# Every entity route file calls `register_entity(SPEC)` at import time
# (see `src/framework/dispatch/registry.py`). The package import above
# (`from src.domain import routes`) executes those calls. Mounting is
# then a single iteration over `entity_registry` — no `include_router`
# line to forget per entity. Owned-subentity specs mount nested under
# their parent's route file and are not registered here.
# Tags come from each spec's `BaseRouter.default_tags`
# (`register_entity` sets them to `[spec.url_collection]`); no need to
# repeat them on `include_router`.
for _, _router in entity_registry.entries():
    app.include_router(_router)

# Dev-only routes. Mounted iff `ENVIRONMENT == "development"`; the
# `/dev/login-as-seed-user` shortcut doesn't exist in production. The
# `mount_dev_routes` indirection makes the gating behavior testable
# without monkeypatching the global `app` instance. See
# `src/domain/routes/dev/dev_auth.py` for the full security rationale.
dev_auth.mount_dev_routes(app, environment=settings.ENVIRONMENT)
dev_components.mount_dev_components(app, environment=settings.ENVIRONMENT)

# Static assets. Two mounts keep the framework/domain CSS boundary
# visible at the URL level — framework primitives at /static/fw/,
# site-specific styles at /static/domain/. Both directories are under
# src/ so the files live next to the code they describe.
#
# Production uses `MinifyingStaticFiles` so .css responses go through
# the in-process minifier (~30% byte savings, Lighthouse: "minify-css"
# audit). Dev keeps the bare `StaticFiles` so DevTools shows readable
# source — the no-cache middleware above already prevents the browser
# from stale-caching dev edits.
_StaticFilesCls = (
    StaticFiles if settings.ENVIRONMENT == "development" else MinifyingStaticFiles
)
app.mount(
    "/static/fw", _StaticFilesCls(directory="src/framework/static"), name="static_fw"
)
app.mount(
    "/static/domain",
    _StaticFilesCls(directory="src/domain/static"),
    name="static_domain",
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
