"""Route-layer tests for the kind-discriminated `/posts` API.

`Post` is polymorphic on `kind`: `client_referral` (multi-section intake
form: Client Location / Demographics / Description / Services / Insurance)
and `provider_availability` (multi-section intake form: Provider Information
/ Location / Availability / Featured Services / Insurance) each have their
own child table (joined-table inheritance — see `src/models/post.py`).
These tests confirm:

- both kinds round-trip through POST/GET/PATCH/DELETE
- the unified GET /posts timeline returns rows of every kind
- the schema's discriminated unions reject unknown / missing kinds and
  enforce per-kind required fields
- both kinds have working PATCH + edit-form flows
- audit rows snapshot kind + per-kind fields alongside the owner
"""

import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import AuditLog, ClientReferral, Post, ProviderAvailability, User
from src.repositories.audit_repository import AuditRepository
from tests.helpers import create_test_user, promote_to_admin

pytestmark = pytest.mark.asyncio


_DEFAULT_DESIRED_TIMES = ["monday_morning", "wednesday_evening"]
_DEFAULT_SERVICES = ["psychotherapy", "case_management"]
_DEFAULT_PA_SETTINGS = ["outpatient", "iop"]


def _make_client_referral(
    owner: User,
    *,
    location_city: str = "Northampton",
    location_state: str = "MA",
    location_zip: str = "01060",
    location_in_person: str = "yes",
    location_virtual: str = "please_contact",
    desired_times: list[str] | None = None,
    client_dem_ages: str = "adults_25_64",
    language_preferred: str = "no",
    description: str = "needs placement",
    services: list[str] | None = None,
    services_psychotherapy_modality: str | None = "DBT",
    insurance: str = "in_network",
) -> ClientReferral:
    return ClientReferral(
        kind="client_referral",
        owner_id=owner.id,
        location_city=location_city,
        location_state=location_state,
        location_zip=location_zip,
        location_in_person=location_in_person,
        location_virtual=location_virtual,
        desired_times=(
            desired_times if desired_times is not None else list(_DEFAULT_DESIRED_TIMES)
        ),
        client_dem_ages=client_dem_ages,
        language_preferred=language_preferred,
        description=description,
        services=services if services is not None else list(_DEFAULT_SERVICES),
        services_psychotherapy_modality=services_psychotherapy_modality,
        insurance=insurance,
    )


def _make_provider_availability(
    owner: User,
    *,
    practice_name: str = "Bedlam Clinic",
    available_providers: str = "Dr. A, Dr. B",
    location_city: str = "Northampton",
    location_state: str = "MA",
    location_zip: str = "01060",
    in_person_sessions: str = "yes",
    virtual_sessions: str = "please_contact",
    desired_times: list[str] | None = None,
    services: list[str] | None = None,
    treatment_modality: str | None = "DBT",
    settings: list[str] | None = None,
    client_focus: str = "adults seeking trauma-informed care",
    age_group: str = "adults_25_64",
    non_english_services: str = "no",
    payment_situation: str = "in_network",
    sliding_scale: bool = True,
    cost: str | None = "$150 per session",
) -> ProviderAvailability:
    return ProviderAvailability(
        kind="provider_availability",
        owner_id=owner.id,
        practice_name=practice_name,
        available_providers=available_providers,
        location_city=location_city,
        location_state=location_state,
        location_zip=location_zip,
        in_person_sessions=in_person_sessions,
        virtual_sessions=virtual_sessions,
        desired_times=(
            desired_times if desired_times is not None else list(_DEFAULT_DESIRED_TIMES)
        ),
        services=services if services is not None else list(_DEFAULT_SERVICES),
        treatment_modality=treatment_modality,
        settings=settings if settings is not None else list(_DEFAULT_PA_SETTINGS),
        client_focus=client_focus,
        age_group=age_group,
        non_english_services=non_english_services,
        payment_situation=payment_situation,
        sliding_scale=sliding_scale,
        cost=cost,
    )


_VALID_CLIENT_REFERRAL_PAYLOAD = {
    "kind": "client_referral",
    "location_city": "Northampton",
    "location_state": "MA",
    "location_zip": "01060",
    "location_in_person": "yes",
    "location_virtual": "please_contact",
    "desired_times": list(_DEFAULT_DESIRED_TIMES),
    "client_dem_ages": "adults_25_64",
    "language_preferred": "no",
    "description": "looking for outpatient placement",
    "services": list(_DEFAULT_SERVICES),
    "services_psychotherapy_modality": "DBT",
    "insurance": "in_network",
}

_VALID_PROVIDER_AVAILABILITY_PAYLOAD = {
    "kind": "provider_availability",
    "practice_name": "Bedlam Clinic",
    "available_providers": "Dr. A, Dr. B",
    "location_city": "Northampton",
    "location_state": "MA",
    "location_zip": "01060",
    "in_person_sessions": "yes",
    "virtual_sessions": "please_contact",
    "desired_times": list(_DEFAULT_DESIRED_TIMES),
    "services": list(_DEFAULT_SERVICES),
    "treatment_modality": "DBT",
    "settings": list(_DEFAULT_PA_SETTINGS),
    "client_focus": "adults seeking trauma-informed care",
    "age_group": "adults_25_64",
    "non_english_services": "no",
    "payment_situation": "in_network",
    "sliding_scale": True,
    "cost": "$150 per session",
}


def _client_referral_audit_snapshot(
    owner_id: uuid.UUID,
    *,
    location_city: str = "Northampton",
    location_state: str = "MA",
    location_zip: str = "01060",
    location_in_person: str = "yes",
    location_virtual: str = "please_contact",
    desired_times: list[str] | None = None,
    client_dem_ages: str = "adults_25_64",
    language_preferred: str = "no",
    description: str = "needs placement",
    services: list[str] | None = None,
    services_psychotherapy_modality: str | None = "DBT",
    insurance: str = "in_network",
) -> dict:
    """Build the expected `before`/`after` audit dict for a client_referral.

    Mirrors `PostAuditSnapshot`; provider_availability fields stay None.
    """
    return {
        "kind": "client_referral",
        "owner_id": str(owner_id),
        "location_city": location_city,
        "location_state": location_state,
        "location_zip": location_zip,
        "location_in_person": location_in_person,
        "location_virtual": location_virtual,
        "desired_times": (
            desired_times if desired_times is not None else list(_DEFAULT_DESIRED_TIMES)
        ),
        "client_dem_ages": client_dem_ages,
        "language_preferred": language_preferred,
        "description": description,
        "services": services if services is not None else list(_DEFAULT_SERVICES),
        "services_psychotherapy_modality": services_psychotherapy_modality,
        "insurance": insurance,
        # provider_availability fields stay None on a client_referral snapshot.
        "practice_name": None,
        "available_providers": None,
        "in_person_sessions": None,
        "virtual_sessions": None,
        "treatment_modality": None,
        "settings": None,
        "client_focus": None,
        "age_group": None,
        "non_english_services": None,
        "payment_situation": None,
        "sliding_scale": None,
        "cost": None,
    }


def _provider_availability_audit_snapshot(
    owner_id: uuid.UUID,
    *,
    practice_name: str = "Bedlam Clinic",
    available_providers: str = "Dr. A, Dr. B",
    location_city: str = "Northampton",
    location_state: str = "MA",
    location_zip: str = "01060",
    in_person_sessions: str = "yes",
    virtual_sessions: str = "please_contact",
    desired_times: list[str] | None = None,
    services: list[str] | None = None,
    treatment_modality: str | None = "DBT",
    settings: list[str] | None = None,
    client_focus: str = "adults seeking trauma-informed care",
    age_group: str = "adults_25_64",
    non_english_services: str = "no",
    payment_situation: str = "in_network",
    sliding_scale: bool = True,
    cost: str | None = "$150 per session",
) -> dict:
    """Build the expected `before`/`after` audit dict for a provider_availability.

    Mirrors `PostAuditSnapshot`; client_referral-only fields stay None.
    """
    return {
        "kind": "provider_availability",
        "owner_id": str(owner_id),
        # client_referral-only fields stay None on a provider_availability
        # snapshot. Shared field names (location_city/state/zip,
        # desired_times, services) appear on both kinds.
        "location_in_person": None,
        "location_virtual": None,
        "client_dem_ages": None,
        "language_preferred": None,
        "description": None,
        "services_psychotherapy_modality": None,
        "insurance": None,
        # provider_availability fields
        "practice_name": practice_name,
        "available_providers": available_providers,
        "location_city": location_city,
        "location_state": location_state,
        "location_zip": location_zip,
        "in_person_sessions": in_person_sessions,
        "virtual_sessions": virtual_sessions,
        "desired_times": (
            desired_times if desired_times is not None else list(_DEFAULT_DESIRED_TIMES)
        ),
        "services": services if services is not None else list(_DEFAULT_SERVICES),
        "treatment_modality": treatment_modality,
        "settings": settings if settings is not None else list(_DEFAULT_PA_SETTINGS),
        "client_focus": client_focus,
        "age_group": age_group,
        "non_english_services": non_english_services,
        "payment_situation": payment_situation,
        "sliding_scale": sliding_scale,
        "cost": cost,
    }


# --- Listing -------------------------------------------------------------


async def test_list_posts_empty(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    tree = HTMLParser(response.text)
    assert "No posts found" in tree.body.text()


async def test_list_posts_shows_both_kinds(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"author-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(
                _make_client_referral(other, description="referral-description")
            )
            session.add(_make_provider_availability(other))

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    items = tree.css("ul > li")
    assert len(items) == 2
    kinds_in_dom = {
        node.attributes.get("data-kind") for node in tree.css("span.post-kind")
    }
    assert kinds_in_dom == {"client_referral", "provider_availability"}
    # The client_referral row's link text uses its description.
    assert "referral-description" in tree.body.text()


async def test_list_posts_orders_newest_first(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    from datetime import datetime, timedelta, timezone

    author = create_test_user(username=f"author-{uuid.uuid4()}")
    older = _make_client_referral(author)
    newer = _make_provider_availability(author)
    now = datetime.now(timezone.utc)
    older.created_at = now - timedelta(days=1)
    newer.created_at = now

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(older)
            session.add(newer)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    items = tree.css("ul > li")
    assert len(items) == 2
    assert "provider_availability" in items[0].text()
    assert "client_referral" in items[1].text()


async def test_list_posts_unauthenticated_redirects(test_client: AsyncClient):
    response = await test_client.get(
        "/posts", headers={"accept": "text/html"}, follow_redirects=False
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]
    assert "next=/posts" in response.headers["location"]


# --- Detail page ---------------------------------------------------------


async def test_detail_renders_client_referral_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _make_client_referral(
        author,
        description="placement",
        location_city="Boston",
        location_state="NY",
        insurance="out_of_network",
        desired_times=["tuesday_afternoon", "friday_evening"],
        services=["evaluation"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert "client_referral" in response.text
    assert tree.css_first(".post-description").text(strip=True) == "placement"
    assert tree.css_first(".post-location-city").text(strip=True) == "Boston"
    assert tree.css_first(".post-location-state").text(strip=True) == "NY"

    insurance = tree.css_first(".post-insurance")
    assert insurance.attributes.get("data-insurance") == "out_of_network"

    time_slots = {
        node.attributes.get("data-time-slot")
        for node in tree.css(".post-desired-times li")
    }
    assert time_slots == {"tuesday_afternoon", "friday_evening"}

    services = {
        node.attributes.get("data-service") for node in tree.css(".post-services li")
    }
    assert services == {"evaluation"}


async def test_detail_renders_provider_availability_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _make_provider_availability(
        author,
        practice_name="Bedlam Clinic",
        location_city="Boston",
        location_state="NY",
        payment_situation="out_of_network",
        sliding_scale=False,
        settings=["residential"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert "provider_availability" in response.text
    assert tree.css_first(".post-practice-name").text(strip=True) == "Bedlam Clinic"
    assert tree.css_first(".post-location-city").text(strip=True) == "Boston"
    assert tree.css_first(".post-location-state").text(strip=True) == "NY"

    payment = tree.css_first(".post-payment-situation")
    assert payment.attributes.get("data-payment-situation") == "out_of_network"

    sliding = tree.css_first(".post-sliding-scale")
    assert sliding.attributes.get("data-sliding-scale") == "false"
    assert sliding.text(strip=True) == "no"

    settings = {
        node.attributes.get("data-setting") for node in tree.css(".post-settings li")
    }
    assert settings == {"residential"}


async def test_get_post_detail_404(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get(f"/posts/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_get_post_detail_malformed_uuid_422(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get("/posts/not-a-uuid")
    assert response.status_code == 422


# --- Create --------------------------------------------------------------


async def test_create_client_referral_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post(
        "/posts", json=_VALID_CLIENT_REFERRAL_PAYLOAD
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])
    assert response.headers.get("Location") == f"/posts/{new_id}"

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == new_id)
        )
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.kind == "client_referral"
        assert persisted.owner_id == logged_in_user.id
        assert persisted.location_city == "Northampton"
        assert persisted.location_state == "MA"
        assert persisted.location_zip == "01060"
        assert persisted.location_in_person == "yes"
        assert persisted.location_virtual == "please_contact"
        assert persisted.desired_times == _DEFAULT_DESIRED_TIMES
        assert persisted.client_dem_ages == "adults_25_64"
        assert persisted.language_preferred == "no"
        assert persisted.description == "looking for outpatient placement"
        assert persisted.services == _DEFAULT_SERVICES
        assert persisted.services_psychotherapy_modality == "DBT"
        assert persisted.insurance == "in_network"


async def test_create_client_referral_allows_empty_multiselects(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Form-submitted payloads omit `desired_times` / `services` when no
    checkbox is ticked — schema defaults both to `[]`."""
    payload = {**_VALID_CLIENT_REFERRAL_PAYLOAD}
    payload.pop("desired_times")
    payload.pop("services")
    payload.pop("services_psychotherapy_modality")

    response = await authenticated_client.post("/posts", json=payload)
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == new_id)
        )
        persisted = result.scalars().first()
        assert persisted.desired_times == []
        assert persisted.services == []
        assert persisted.services_psychotherapy_modality is None


async def test_create_provider_availability_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post(
        "/posts", json=_VALID_PROVIDER_AVAILABILITY_PAYLOAD
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ProviderAvailability).filter(ProviderAvailability.id == new_id)
        )
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.kind == "provider_availability"
        assert persisted.owner_id == logged_in_user.id
        assert persisted.practice_name == "Bedlam Clinic"
        assert persisted.available_providers == "Dr. A, Dr. B"
        assert persisted.location_city == "Northampton"
        assert persisted.location_state == "MA"
        assert persisted.location_zip == "01060"
        assert persisted.in_person_sessions == "yes"
        assert persisted.virtual_sessions == "please_contact"
        assert persisted.desired_times == _DEFAULT_DESIRED_TIMES
        assert persisted.services == _DEFAULT_SERVICES
        assert persisted.treatment_modality == "DBT"
        assert persisted.settings == _DEFAULT_PA_SETTINGS
        assert persisted.client_focus == "adults seeking trauma-informed care"
        assert persisted.age_group == "adults_25_64"
        assert persisted.non_english_services == "no"
        assert persisted.payment_situation == "in_network"
        assert persisted.sliding_scale is True
        assert persisted.cost == "$150 per session"


async def test_create_post_strips_whitespace(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    payload = {
        **_VALID_CLIENT_REFERRAL_PAYLOAD,
        "location_city": "  Boston  ",
        "description": "  needs help  ",
    }
    response = await authenticated_client.post("/posts", json=payload)
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == new_id)
        )
        persisted = result.scalars().first()
        assert persisted.location_city == "Boston"
        assert persisted.description == "needs help"


async def test_create_post_rejects_owner_id_in_payload(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)

    response = await authenticated_client.post(
        "/posts",
        json={**_VALID_CLIENT_REFERRAL_PAYLOAD, "owner_id": str(other.id)},
    )
    assert response.status_code == 422

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post))
        assert result.scalars().first() is None


async def test_create_post_rejects_unknown_field(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.post(
        "/posts", json={**_VALID_CLIENT_REFERRAL_PAYLOAD, "summary": "old"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"kind": "not_a_real_kind"},
        # client_referral missing required fields
        {"kind": "client_referral"},
        # bad enum values
        {**_VALID_CLIENT_REFERRAL_PAYLOAD, "location_state": "ZZ"},
        {**_VALID_CLIENT_REFERRAL_PAYLOAD, "insurance": "self_pay"},
        {**_VALID_CLIENT_REFERRAL_PAYLOAD, "client_dem_ages": "EVERYONE"},
        # bad zip
        {**_VALID_CLIENT_REFERRAL_PAYLOAD, "location_zip": "1234"},
        # whitespace-only required fields
        {**_VALID_CLIENT_REFERRAL_PAYLOAD, "description": "   "},
        # bad multiselect element
        {**_VALID_CLIENT_REFERRAL_PAYLOAD, "services": ["telepathy"]},
    ],
)
async def test_create_post_rejects_invalid_payload(
    payload,
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.post("/posts", json=payload)
    assert response.status_code == 422


async def test_create_post_unauthenticated_redirects(test_client: AsyncClient):
    response = await test_client.post(
        "/posts",
        json=_VALID_CLIENT_REFERRAL_PAYLOAD,
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


# --- Update (PATCH) ------------------------------------------------------


async def test_owner_can_patch_description_only(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(
        logged_in_user, description="orig", location_city="orig-city"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={"kind": "client_referral", "description": "new"},
    )
    assert response.status_code == 200
    assert response.headers.get("HX-Refresh") == "true"

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == post.id)
        )
        refreshed = result.scalars().first()
        assert refreshed.description == "new"
        assert refreshed.location_city == "orig-city"  # untouched


async def test_owner_can_patch_multiple_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={
            "kind": "client_referral",
            "description": "D2",
            "insurance": "out_of_network",
            "location_state": "NY",
            "services": ["evaluation"],
        },
    )
    assert response.status_code == 200

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == post.id)
        )
        refreshed = result.scalars().first()
        assert refreshed.description == "D2"
        assert refreshed.insurance == "out_of_network"
        assert refreshed.location_state == "NY"
        assert refreshed.services == ["evaluation"]


async def test_non_owner_cannot_patch_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other, description="orig")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={"kind": "client_referral", "description": "hijack"},
    )
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == post.id)
        )
        refreshed = result.scalars().first()
        assert refreshed.description == "orig"


async def test_admin_can_patch_anyone_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other, description="orig")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={"kind": "client_referral", "description": "moderated"},
    )
    assert response.status_code == 200


async def test_patch_404_for_unknown_post(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.patch(
        f"/posts/{uuid.uuid4()}",
        json={"kind": "client_referral", "description": "x"},
    )
    assert response.status_code == 404


async def test_patch_kind_mismatch_returns_400(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The body's kind discriminator must match the persisted post's kind —
    a PATCH cannot repurpose a post's identity."""
    post = _make_provider_availability(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={"kind": "client_referral", "description": "x"},
    )
    assert response.status_code == 400


async def test_owner_can_patch_provider_availability(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_provider_availability(
        logged_in_user,
        practice_name="orig",
        location_city="orig-city",
        sliding_scale=True,
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={
            "kind": "provider_availability",
            "practice_name": "P2",
            "sliding_scale": False,
        },
    )
    assert response.status_code == 200

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ProviderAvailability).filter(ProviderAvailability.id == post.id)
        )
        refreshed = result.scalars().first()
        assert refreshed.practice_name == "P2"
        assert refreshed.location_city == "orig-city"  # untouched
        assert refreshed.sliding_scale is False


async def test_patch_rejects_owner_id_in_payload(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(logged_in_user)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={
            "kind": "client_referral",
            "description": "d",
            "owner_id": str(other.id),
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "patch_body",
    [
        {},
        {"kind": "client_referral"},
        {"kind": "client_referral", "description": "   "},
        {
            "kind": "client_referral",
            "description": None,
            "insurance": None,
            "location_state": None,
        },
        {"kind": "client_referral", "insurance": "self_pay"},
        {"kind": "client_referral", "location_zip": "12"},
    ],
)
async def test_patch_invalid_body_422(
    patch_body,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(f"/posts/{post.id}", json=patch_body)
    assert response.status_code == 422


async def test_patch_unauthenticated_redirects(test_client: AsyncClient):
    response = await test_client.patch(
        f"/posts/{uuid.uuid4()}",
        json={"kind": "client_referral", "description": "x"},
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


# --- Create form page (GET /posts/form) ----------------------------------


async def test_get_post_form_renders_kind_and_field_clusters(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get("/posts/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-post") == "/posts"
    assert form.attributes.get("hx-ext") == "json-enc-arrays"
    assert form.attributes.get("data-json-enc-array-fields") == "desired_times services"

    kinds_offered = {
        node.attributes.get("value")
        for node in tree.css('input[type="radio"][name="kind"]')
    }
    assert kinds_offered == {"client_referral", "provider_availability"}

    # client_referral cluster has all five sections.
    cr_cluster = tree.css_first('[data-kind-fields="client_referral"]')
    assert cr_cluster is not None
    assert cr_cluster.css_first('input[name="location_city"]') is not None
    assert cr_cluster.css_first('select[name="location_state"]') is not None
    assert cr_cluster.css_first('input[name="location_zip"]') is not None
    assert cr_cluster.css_first('select[name="location_in_person"]') is not None
    assert cr_cluster.css_first('select[name="location_virtual"]') is not None
    # 21 desired_times checkboxes
    cr_desired = cr_cluster.css('input[type="checkbox"][name="desired_times"]')
    assert len(cr_desired) == 21
    assert cr_cluster.css_first('select[name="client_dem_ages"]') is not None
    assert cr_cluster.css_first('select[name="language_preferred"]') is not None
    assert cr_cluster.css_first('textarea[name="description"]') is not None
    # 5 service checkboxes
    cr_services = cr_cluster.css('input[type="checkbox"][name="services"]')
    assert len(cr_services) == 5
    assert (
        cr_cluster.css_first('input[name="services_psychotherapy_modality"]')
        is not None
    )
    assert cr_cluster.css_first('select[name="insurance"]') is not None

    # provider_availability cluster has all five sections.
    pa_cluster = tree.css_first('[data-kind-fields="provider_availability"]')
    assert pa_cluster is not None
    assert pa_cluster.css_first('input[name="practice_name"]') is not None
    assert pa_cluster.css_first('input[name="available_providers"]') is not None
    assert pa_cluster.css_first('input[name="location_city"]') is not None
    assert pa_cluster.css_first('select[name="location_state"]') is not None
    assert pa_cluster.css_first('input[name="location_zip"]') is not None
    assert pa_cluster.css_first('select[name="in_person_sessions"]') is not None
    assert pa_cluster.css_first('select[name="virtual_sessions"]') is not None
    pa_desired = pa_cluster.css('input[type="checkbox"][name="desired_times"]')
    assert len(pa_desired) == 21
    pa_services = pa_cluster.css('input[type="checkbox"][name="services"]')
    assert len(pa_services) == 5
    pa_settings = pa_cluster.css('input[type="checkbox"][name="settings"]')
    assert len(pa_settings) == 5
    assert pa_cluster.css_first('input[name="treatment_modality"]') is not None
    assert pa_cluster.css_first('textarea[name="client_focus"]') is not None
    assert pa_cluster.css_first('select[name="age_group"]') is not None
    assert pa_cluster.css_first('select[name="non_english_services"]') is not None
    assert pa_cluster.css_first('select[name="payment_situation"]') is not None
    sliding_radios = pa_cluster.css('input[type="radio"][name="sliding_scale"]')
    assert {r.attributes.get("value") for r in sliding_radios} == {"true", "false"}
    assert pa_cluster.css_first('input[name="cost"]') is not None


async def test_get_post_form_unauthenticated_redirects(test_client: AsyncClient):
    response = await test_client.get(
        "/posts/form",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]
    assert "next=/posts/form" in response.headers["location"]


async def test_form_route_does_not_shadow_detail_route(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    assert "client_referral" in response.text


async def test_list_page_links_to_create_form(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    link = tree.css_first('a[href="/posts/form"]')
    assert link is not None
    assert "New post" in link.text()


# --- Edit form page (GET /posts/{id}/form) -------------------------------


async def test_owner_can_open_client_referral_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(
        logged_in_user,
        description="orig description",
        location_city="orig-city",
        location_state="NY",
        insurance="out_of_network",
        desired_times=["thursday_morning"],
        services=["evaluation"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-patch") == f"/posts/{post.id}"

    description = tree.css_first('textarea[name="description"]')
    assert description is not None
    assert "orig description" in description.text()

    state = tree.css_first('select[name="location_state"] option[selected]')
    assert state is not None
    assert state.attributes.get("value") == "NY"

    insurance = tree.css_first('select[name="insurance"] option[selected]')
    assert insurance is not None
    assert insurance.attributes.get("value") == "out_of_network"

    city = tree.css_first('input[name="location_city"]')
    assert city is not None
    assert city.attributes.get("value") == "orig-city"

    checked_times = {
        node.attributes.get("value")
        for node in tree.css('input[type="checkbox"][name="desired_times"]')
        if "checked" in node.attributes
    }
    assert checked_times == {"thursday_morning"}

    checked_services = {
        node.attributes.get("value")
        for node in tree.css('input[type="checkbox"][name="services"]')
        if "checked" in node.attributes
    }
    assert checked_services == {"evaluation"}

    # Hidden discriminator so the PATCH body carries the right `kind`.
    discriminator = tree.css_first('input[type="hidden"][name="kind"]')
    assert discriminator is not None
    assert discriminator.attributes.get("value") == "client_referral"


async def test_admin_can_open_edit_form_for_any_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200


async def test_non_owner_cannot_open_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 403


async def test_edit_form_404_for_unknown_post(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get(f"/posts/{uuid.uuid4()}/form")
    assert response.status_code == 404


async def test_owner_can_open_provider_availability_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_provider_availability(
        logged_in_user,
        practice_name="orig-practice",
        available_providers="orig-providers",
        location_state="NY",
        payment_situation="out_of_network",
        sliding_scale=False,
        settings=["residential"],
        services=["evaluation"],
        desired_times=["thursday_morning"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-patch") == f"/posts/{post.id}"
    assert form.attributes.get("hx-ext") == "json-enc-arrays"
    assert (
        form.attributes.get("data-json-enc-array-fields")
        == "desired_times services settings"
    )

    discriminator = tree.css_first('input[type="hidden"][name="kind"]')
    assert discriminator.attributes.get("value") == "provider_availability"

    practice = tree.css_first('input[name="practice_name"]')
    assert practice.attributes.get("value") == "orig-practice"
    providers = tree.css_first('input[name="available_providers"]')
    assert providers.attributes.get("value") == "orig-providers"

    state = tree.css_first('select[name="location_state"] option[selected]')
    assert state.attributes.get("value") == "NY"

    payment = tree.css_first('select[name="payment_situation"] option[selected]')
    assert payment.attributes.get("value") == "out_of_network"

    sliding_no = tree.css_first(
        'input[type="radio"][name="sliding_scale"][value="false"][checked]'
    )
    assert sliding_no is not None

    checked_settings = {
        node.attributes.get("value")
        for node in tree.css('input[type="checkbox"][name="settings"]')
        if "checked" in node.attributes
    }
    assert checked_settings == {"residential"}

    checked_services = {
        node.attributes.get("value")
        for node in tree.css('input[type="checkbox"][name="services"]')
        if "checked" in node.attributes
    }
    assert checked_services == {"evaluation"}

    checked_times = {
        node.attributes.get("value")
        for node in tree.css('input[type="checkbox"][name="desired_times"]')
        if "checked" in node.attributes
    }
    assert checked_times == {"thursday_morning"}


async def test_edit_form_unauthenticated_redirects(test_client: AsyncClient):
    response = await test_client.get(
        f"/posts/{uuid.uuid4()}/form",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


# --- Owner-actions partial visibility on detail page ---------------------


async def test_detail_shows_edit_link_for_client_referral_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    actions = tree.css_first("span.owner-actions")
    assert actions is not None
    assert actions.css_first(f'a[href="/posts/{post.id}/form"]') is not None


async def test_detail_shows_edit_link_for_provider_availability_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_provider_availability(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    actions = tree.css_first("span.owner-actions")
    assert actions is not None
    assert actions.css_first(f'a[href="/posts/{post.id}/form"]') is not None


async def test_detail_hides_owner_actions_for_stranger(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("span.owner-actions") is None


async def test_detail_delete_button_for_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    button = tree.css_first("span.owner-actions button")
    assert button is not None
    assert button.text().strip() == "Delete"
    assert button.attributes.get("hx-delete") == f"/posts/{post.id}"
    assert button.attributes.get("hx-confirm")


# --- Audit log -----------------------------------------------------------


async def test_create_client_referral_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post(
        "/posts", json=_VALID_CLIENT_REFERRAL_PAYLOAD
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=new_id)
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_id == logged_in_user.id
        assert row.action == "create_post"
        assert row.before is None
        assert row.after == _client_referral_audit_snapshot(
            logged_in_user.id,
            description="looking for outpatient placement",
        )


async def test_create_provider_availability_audit_includes_kind_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The audit snapshot is shape-uniform across kinds: each kind's fields
    fill in the snapshot, the rest stay None."""
    response = await authenticated_client.post(
        "/posts", json=_VALID_PROVIDER_AVAILABILITY_PAYLOAD
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=new_id)
        assert len(rows) == 1
        assert rows[0].after == _provider_availability_audit_snapshot(logged_in_user.id)


async def test_patch_writes_audit_row_with_before_and_after(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(
        logged_in_user, description="orig", insurance="in_network"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={
            "kind": "client_referral",
            "description": "new",
            "insurance": "out_of_network",
        },
    )
    assert response.status_code == 200

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post.id)
        assert len(rows) == 1
        row = rows[0]
        assert row.action == "update_post"
        assert row.before == _client_referral_audit_snapshot(
            logged_in_user.id, description="orig", insurance="in_network"
        )
        assert row.after == _client_referral_audit_snapshot(
            logged_in_user.id, description="new", insurance="out_of_network"
        )


async def test_failed_create_writes_no_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post("/posts", json={"kind": "not_a_kind"})
    assert response.status_code == 422

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(AuditLog).filter(AuditLog.resource_type == "post")
        )
        assert result.scalars().first() is None


async def test_unauthorized_patch_writes_no_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={"kind": "client_referral", "description": "hijack"},
    )
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post.id)
        assert rows == []


# --- Delete (DELETE) -----------------------------------------------------


async def test_owner_can_delete_own_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.delete(f"/posts/{post.id}")
    assert response.status_code == 204
    assert response.headers.get("HX-Redirect") == "/posts"

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        assert result.scalars().first() is None
        # Child row cascades.
        child = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == post.id)
        )
        assert child.scalars().first() is None


async def test_admin_can_delete_anyone_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_provider_availability(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.delete(f"/posts/{post.id}")
    assert response.status_code == 204


async def test_non_owner_cannot_delete_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.delete(f"/posts/{post.id}")
    assert response.status_code == 403


async def test_delete_404_for_unknown_post(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.delete(f"/posts/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_delete_unauthenticated_redirects(test_client: AsyncClient):
    response = await test_client.delete(
        f"/posts/{uuid.uuid4()}",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


async def test_delete_post_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(
        logged_in_user, description="doomed", insurance="in_network"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
    post_id = post.id

    response = await authenticated_client.delete(f"/posts/{post_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post_id)
        assert len(rows) == 1
        row = rows[0]
        assert row.action == "delete_post"
        assert row.before == _client_referral_audit_snapshot(
            logged_in_user.id, description="doomed", insurance="in_network"
        )
        assert row.after is None
