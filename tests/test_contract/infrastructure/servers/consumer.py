"""Consumer server management for contract tests.

The consumer server hosts only the HTML page(s) whose form submission is the
contract under test. It is deliberately minimal — Playwright drives a browser
against it, intercepts the outbound API call, and forwards it to the Pact mock
service. Anything that talks to a real database or service is out of scope.
"""

import logging
import uuid
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request

from src.api.common import APIResponse
from src.api.routes import auth_pages
from src.auth_config import current_active_user, current_admin_user

from ..utilities.mocks import MockAuthManager, create_mock_user
from .base import ServerManager, setup_health_check_route

# Stable UUID used by the admin-actions stub page so consumer tests can build
# the pact path against a known target id without round-tripping a database.
STUB_TARGET_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

# Stable UUID used by the post-edit stub page; matches `STUB_POST_ID` in
# `tests/test_contract/constants.py`.
STUB_POST_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


class ConsumerServerConfig:
    """Toggles for which page routes the consumer server should mount.

    Add a new flag (and a matching `app.include_router(...)` call in
    `setup_consumer_app_routes`) when introducing a contract test pair for a
    new HTML form.
    """

    def __init__(
        self,
        auth_pages: bool = True,
        users_admin_actions: bool = False,
        posts_pages: bool = False,
        posts_owner_actions: bool = False,
        mock_auth: bool = True,
    ):
        self.auth_pages = auth_pages
        self.users_admin_actions = users_admin_actions
        self.posts_pages = posts_pages
        self.posts_owner_actions = posts_owner_actions
        self.mock_auth = mock_auth


def _setup_users_admin_actions_stub(app: FastAPI) -> None:
    """Mount a stub page that renders the real `users/detail.html` template
    with hardcoded admin and target user objects, so the admin-actions partial
    is exercised without needing a database. The contract surface is the
    HTMX-decorated buttons inside the partial; what we render here is the same
    partial production code paths render.
    """

    class _StubUser:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @app.get("/users/{target_user_id}")
    async def admin_actions_stub_page(request: Request, target_user_id: uuid.UUID):
        target_user = _StubUser(
            id=target_user_id,
            username="target_user",
            email="target@example.com",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        # The page route relies on `current_user` being set in context; the
        # mocked `current_active_user` dependency above places it on
        # request.state via fastapi-users, but for the stub we pass it directly.
        current_user = _StubUser(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            username="admin_user",
            is_superuser=True,
        )
        return APIResponse.html_response(
            template_name="users/detail.html",
            context={"target_user": target_user, "current_user": current_user},
            request=request,
        )


def _setup_posts_form_stub(app: FastAPI) -> None:
    """Mount stub pages that render the real post form templates. The
    contract surface is the forms' HTMX-decorated submissions; the create
    POST and edit PATCH are intercepted by Playwright before they leave the
    browser, so no database is needed.

    The edit-form stub key is the path's query string `?kind=...` — keeping
    a single edit route avoids two stub UUIDs while letting each per-kind
    edit pact pick the template it needs.
    """

    class _StubPost:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    def _client_referral_stub(post_id: uuid.UUID) -> _StubPost:
        return _StubPost(
            id=post_id,
            kind="client_referral",
            location_city="Northampton",
            location_state="MA",
            location_zip="01060",
            location_in_person="yes",
            location_virtual="please_contact",
            desired_times=["monday_morning", "wednesday_evening"],
            client_dem_ages="adults_25_64",
            language_preferred="no",
            description="Stub description",
            services=["psychotherapy", "case_management"],
            services_psychotherapy_modality="DBT",
            insurance="in_network",
        )

    def _provider_availability_stub(post_id: uuid.UUID) -> _StubPost:
        return _StubPost(
            id=post_id,
            kind="provider_availability",
            practice_name="Bedlam Clinic",
            available_providers="Dr. A, Dr. B",
            location_city="Northampton",
            location_state="MA",
            location_zip="01060",
            in_person_sessions="yes",
            virtual_sessions="please_contact",
            desired_times=["monday_morning", "wednesday_evening"],
            services=["psychotherapy", "evaluation"],
            treatment_modality="DBT",
            settings=["outpatient", "iop"],
            client_focus="adults seeking trauma-informed care",
            age_group="adults_25_64",
            non_english_services="no",
            payment_situation="in_network",
            sliding_scale=True,
            cost="$150 per session",
        )

    @app.get("/posts/form")
    async def posts_form_stub_page(request: Request):
        return APIResponse.html_response(
            template_name="posts/new.html", context={}, request=request
        )

    @app.get("/posts/{post_id}/form")
    async def posts_edit_form_stub_page(request: Request, post_id: uuid.UUID):
        # `?kind=provider_availability` → render the PA edit template; default
        # to client_referral so existing pacts continue to work without change.
        kind = request.query_params.get("kind", "client_referral")
        if kind == "provider_availability":
            post = _provider_availability_stub(post_id)
            template = "posts/edit_provider_availability.html"
        else:
            post = _client_referral_stub(post_id)
            template = "posts/edit_client_referral.html"
        return APIResponse.html_response(
            template_name=template,
            context={"post": post},
            request=request,
        )


def _setup_post_owner_actions_stub(app: FastAPI) -> None:
    """Mount a stub page that renders the real `posts/detail.html` template
    with hardcoded post + current_user, so the `_owner_actions.html` partial
    is exercised without needing a database. The contract surface is the
    HTMX-decorated Delete button inside the partial; what we render here is
    the same partial production code paths render.
    """

    class _StubUser:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _StubPost:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @app.get("/posts/{post_id}")
    async def post_owner_actions_stub_page(request: Request, post_id: uuid.UUID):
        owner = _StubUser(id=post_id, username="post_owner")
        post = _StubPost(
            id=post_id,
            kind="client_referral",
            owner_id=owner.id,
            owner=owner,
            location_city="Northampton",
            location_state="MA",
            location_zip="01060",
            location_in_person="yes",
            location_virtual="please_contact",
            desired_times=["monday_morning", "wednesday_evening"],
            client_dem_ages="adults_25_64",
            language_preferred="no",
            description="Stub description",
            services=["psychotherapy", "case_management"],
            services_psychotherapy_modality="DBT",
            insurance="in_network",
        )
        # The mock auth in `run_consumer_server_process` makes current_user a
        # superuser when `posts_owner_actions=True`, so the partial's
        # owner-or-admin gate renders the buttons regardless of post.owner_id.
        current_user = _StubUser(
            id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            username="admin_user",
            is_superuser=True,
        )
        return APIResponse.html_response(
            template_name="posts/detail.html",
            context={"post": post, "current_user": current_user},
            request=request,
        )


def setup_consumer_app_routes(app: FastAPI, config: ConsumerServerConfig) -> None:
    if config.auth_pages:
        app.include_router(auth_pages.auth_pages_api_router)
    if config.users_admin_actions:
        _setup_users_admin_actions_stub(app)
    if config.posts_pages:
        _setup_posts_form_stub(app)
    if config.posts_owner_actions:
        _setup_post_owner_actions_stub(app)


def run_consumer_server_process(
    host: str, port: int, config: Optional[ConsumerServerConfig] = None
) -> None:
    logger = logging.getLogger("consumer_server")

    if config is None:
        config = ConsumerServerConfig()

    consumer_app = FastAPI(title="Consumer Test Server Process")
    setup_health_check_route(consumer_app)

    setup_consumer_app_routes(consumer_app, config)

    if config.mock_auth:
        logger.info("Adding mock auth for contract tests")
        # When an admin/owner-actions stub is mounted, the mock user must be
        # a superuser so the partial's `is_superuser` (or owner-or-admin)
        # gate renders the buttons.
        mock_user = create_mock_user(
            email="test@example.com",
            username="contract_test_user",
            is_superuser=config.users_admin_actions or config.posts_owner_actions,
        )
        MockAuthManager.setup_mock_auth(
            consumer_app, mock_user, current_active_user, current_admin_user
        )

    uvicorn.run(consumer_app, host=host, port=port, log_level="warning")


class ConsumerServerManager(ServerManager):
    def start_with_config(self, config: Optional[ConsumerServerConfig] = None) -> None:
        self.start(run_consumer_server_process, config)
