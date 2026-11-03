import uuid
from typing import Any, Optional
from uuid import UUID  # Import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Need ORM models
from src.domain.models import (
    Clinician,
    ClinicianCertification,
    ClinicianEducation,
    ClinicianLicensure,
    IntakeDetail,
    OpeningDetail,
    Organization,
    Program,
    ReferralDetail,
    User,
)


def create_test_user(
    id: Optional[UUID] = None,
    username: Optional[str] = None,
    email: Optional[str] = None,
    hashed_password: Optional[str] = None,
    is_active: bool = True,
    is_superuser: bool = False,
    # `is_verified` is an ORM column required by fastapi-users — it is NOT
    # the same as the API response field (which was removed from `UserRead`
    # in #696). Passing `is_verified=True` here sets the DB column only;
    # it does not affect the JSON response shape. Default True so tests
    # don't need to worry about the verification state.
    is_verified: bool = True,
) -> User:
    """Creates a User ORM instance with default values for testing."""
    unique_suffix = uuid.uuid4()
    return User(
        id=id or unique_suffix,
        username=username or f"testuser_{unique_suffix}",
        email=email or f"test_{unique_suffix}@example.com",
        hashed_password=hashed_password or f"password_{unique_suffix}",
        is_active=is_active,
        is_superuser=is_superuser,
        is_verified=is_verified,
    )


# --- Per-kind detail factories --------------------------------------------
#
# Both per-kind detail tables now have many required columns (see the
# per-kind Pydantic schemas in `src/domain/logic/posts/schema.py`).
# Tests that don't care about the specifics still need a *valid* row to
# exercise route / repo / schema behavior, so these factories supply
# spec-compliant defaults and let callers override per field.

# Stub referring_clinician_id for schema-validation tests that never
# hit the DB. Real round-trip tests pass an actual Clinician's id.
_STUB_REFERRING_CLINICIAN_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

# Stub clinician_affiliation_id — the field the form practice-picker
# submits and from which the server derives the listing's clinician FK.
# Required on the wire Create for both clinician-authored kinds. Schema
# tests use the stub; route/persistence tests pass a real affiliation id.
_STUB_CLINICIAN_AFFILIATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")

# ORM factory defaults: FK fields must be None (nullable columns).
# SQLAlchemy's UUID column type calls .hex on the value — plain strings blow up.
_REFERRAL_ORM_DEFAULTS: dict[str, Any] = {
    "location_city": "Springfield",
    "location_state": "IL",
    "session_format": ["in_person"],
    "age_groups": ["adults_25_64"],
    "languages": ["en"],
    "description": "needs placement",
    "services": [],
    "services_other_text": None,
    "languages_other_text": None,
    "pronouns": [],
    "pronouns_other_text": None,
    "sliding_scale": False,
    "insurance_carriers_other_text": None,
    # Payment paths — a carrier list (non-empty = in-network; no boolean)
    # plus independent private-pay / sliding-scale opt-ins. The ORM default
    # leaves the carrier list empty; the wire default below names one for a
    # representative "Aetna patient" referral.
    "accepts_private_pay": False,
    "insurance_carriers": [],
    # FK fields: always None here. Add stub string UUIDs to _REFERRAL_WIRE_DEFAULTS instead.
    "referring_clinician_id": None,
}

# Wire-payload defaults: FK fields as stub string UUIDs for Pydantic validation.
# Tests that actually persist must override with a real DB-resident ID.
# `clinician_affiliation_id` is the required picker field; `referring_clinician_id`
# is now optional on the wire (server-derived from the affiliation) but kept
# here as a stub so schema round-trip tests still exercise it.
_REFERRAL_WIRE_DEFAULTS: dict[str, Any] = {
    **_REFERRAL_ORM_DEFAULTS,
    # The representative referral is in-network ("Aetna patient"), so the
    # wire payload names a carrier. `insurance_carriers` is always optional
    # now; tests exercising the no-coverage path override it back to `[]`.
    "insurance_carriers": ["aetna"],
    "referring_clinician_id": str(_STUB_REFERRING_CLINICIAN_ID),
    "clinician_affiliation_id": str(_STUB_CLINICIAN_AFFILIATION_ID),
}

# #1358 PR-f sub-3 — OpeningDetail is thin. The steady-state profile
# fields (services / settings / modalities / age_groups / genders /
# languages / website / referral_instructions) live on the linked
# ClinicianAffiliation (and `languages` on the linked Clinician) and
# are set there directly.
_OPENING_DEFAULTS: dict[str, Any] = {
    "description": None,
    "schedule_text": None,
}


def referral_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `kind='referral'` create/update payload.
    Returns a fresh dict each call. `referring_clinician_id` defaults to
    a stub UUID that passes Pydantic validation but does *not* exist in
    the DB — tests that actually persist must pass a real id override."""
    return {"kind": "referral", **_REFERRAL_WIRE_DEFAULTS, **overrides}


# Stub clinician_id for schema-validation tests that never hit the DB.
# Real round-trip tests pass an actual Clinician's id via the kwarg.
_STUB_CLINICIAN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def opening_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `kind='clinician_opening'` create/update payload.
    Returns a fresh dict each call. `clinician_id` defaults to a stub UUID
    that passes Pydantic validation but does *not* exist in the DB —
    tests that actually persist must pass a real clinician_id override."""
    return {
        "kind": "clinician_opening",
        "clinician_id": str(_STUB_CLINICIAN_ID),
        "clinician_affiliation_id": str(_STUB_CLINICIAN_AFFILIATION_ID),
        **_OPENING_DEFAULTS,
        **overrides,
    }


def make_referral_detail(**overrides: Any) -> ReferralDetail:
    """Build a `ReferralDetail` ORM row with spec-compliant defaults."""
    return ReferralDetail(**{**_REFERRAL_ORM_DEFAULTS, **overrides})


# Program-availability mirrors PA's shape: an FK to the target row plus the
# same per-announcement field set. Pydantic-side and ORM-side factories
# below use the same defaults to keep round-trip tests aligned.

# #1358 PR-f sub-3 — IntakeDetail is thin. The steady-state profile
# lives on the linked Program (including `languages`, which is
# program-level on the intake side).
_PROGRAM_AVAILABILITY_DEFAULTS: dict[str, Any] = {
    "description": None,
    "schedule_text": None,
}

# Stub program_id for schema-validation tests that never hit the DB.
# Real round-trip tests pass an actual Program's id via the kwarg.
_STUB_PROGRAM_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def intake_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `kind='program_intake'` create/update payload.
    Returns a fresh dict each call. `program_id` defaults to a stub UUID
    that passes Pydantic validation but does *not* exist in the DB —
    tests that actually persist must pass a real program_id override."""
    return {
        "kind": "program_intake",
        "program_id": str(_STUB_PROGRAM_ID),
        **_PROGRAM_AVAILABILITY_DEFAULTS,
        **overrides,
    }


def make_intake_detail(*, program_id: UUID, **overrides: Any) -> IntakeDetail:
    """Build a `IntakeDetail` ORM row with spec-compliant
    defaults. `program_id` is a required kwarg — making it required
    turns "I forgot the FK" into a `TypeError` at the factory call site
    instead of a `NOT NULL` violation at flush time (mirrors
    :func:`make_opening_detail`)."""
    return IntakeDetail(
        program_id=program_id, **{**_PROGRAM_AVAILABILITY_DEFAULTS, **overrides}
    )


def make_program(
    *, owner_id: UUID, org_id: UUID, name: str = "RISE IOP", **overrides: Any
) -> Program:
    """Build a `Program` ORM row. ``owner_id`` and ``org_id`` are required
    kwargs — both columns are NOT NULL on the model."""
    return Program(owner_id=owner_id, org_id=org_id, name=name, **overrides)


def make_opening_detail(*, clinician_id: UUID, **overrides: Any) -> OpeningDetail:
    """Build a `OpeningDetail` ORM row with spec-compliant
    defaults. `clinician_id` is a required kwarg — PA points at a Clinician,
    and forgetting the FK should be a `TypeError` at construction rather
    than a NOT NULL violation at flush."""
    return OpeningDetail(
        clinician_id=clinician_id, **{**_OPENING_DEFAULTS, **overrides}
    )


# --- Clinician + credential sub-table factories ---------------------------
#
# Defaults supply CHECK-constraint-valid values so tests that don't care
# about credential specifics still produce inserts that pass DB-level
# guards. The owning FK (`owner_id` for clinicians, `clinician_id` for
# sub-rows) is a required keyword-only parameter — making it required
# turns "I forgot the FK" into a `TypeError` at the factory call site
# instead of a `NOT NULL` violation at flush time.

_CLINICIAN_DEFAULTS: dict[str, Any] = {
    "first_name": "Jane",
    "last_name": "Smith",
    "location_city": "Springfield",
    "location_state": "IL",
    # Insurance posture: empty carrier list (no in-network) + OON on by
    # default (matches the model's `server_default`). Tests that need a
    # pure self-pay shape pass `accepts_out_of_network=False` explicitly.
    # Delivery format + cost are per-announcement now (on the opening), no
    # longer affiliation/clinician fields.
    "accepts_out_of_network": True,
    "in_network_carriers": [],
    "sliding_scale": False,
}

# Minimal wire payload — what `POST /clinicians` accepts. Affiliation,
# location, availability, and insurance fields live on `ClinicianAffiliation`
# and are added via the affiliation sub-resource after create.
_CLINICIAN_CREATE_WIRE_DEFAULTS: dict[str, Any] = {
    "first_name": "Jane",
    "last_name": "Smith",
    "npi": "1234567890",
}

_CLINICIAN_LICENSURE_DEFAULTS: dict[str, Any] = {
    "license_type": "lcsw",
    "license_number": "L-12345",
    "issuing_state": "IL",
    "expiration_date": None,
}

_CLINICIAN_EDUCATION_DEFAULTS: dict[str, Any] = {
    "education_type": "msw",
    "institution": "State University",
    "month_completed": None,
}

_CLINICIAN_CERTIFICATION_DEFAULTS: dict[str, Any] = {
    "certification_type": "emdr",
    "certifying_body": "EMDRIA",
    "expiration_date": None,
}


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is `None`. Form-encoded HTTP requests collapse
    `None` to an empty string on the wire, which then 422s any Pydantic
    `T | None` field that can't coerce '' (e.g. `date | None`). The form
    contract is "absent field = leave as default", so dropping `None` keys
    here matches that contract before httpx serializes the dict."""
    return {k: v for k, v in d.items() if v is not None}


def clinician_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `POST /clinicians` form-encoded payload —
    first / last / NPI only. Returns a fresh flat dict each call.
    Affiliation, location, availability, insurance, and credentials are
    added after create via their dedicated sub-resource endpoints."""
    return _drop_none({**_CLINICIAN_CREATE_WIRE_DEFAULTS, **overrides})


def licensure_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `POST /clinicians/{id}/licensures` payload."""
    return _drop_none({**_CLINICIAN_LICENSURE_DEFAULTS, **overrides})


def education_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `POST /clinicians/{id}/educations` payload."""
    return _drop_none({**_CLINICIAN_EDUCATION_DEFAULTS, **overrides})


def certification_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `POST /clinicians/{id}/certifications` payload."""
    return _drop_none({**_CLINICIAN_CERTIFICATION_DEFAULTS, **overrides})


def make_clinician(*, owner_id: UUID, **overrides: Any) -> Clinician:
    """Build a `Clinician` ORM row with CHECK-valid defaults.

    Defaults `clinician_verified=True` + `npi_match_status='matched'` so
    rows are directory-visible by default — handoff §4.3 / §10.6 filter
    the directory on `clinician_verified OR ever_verified_at`. Tests that
    specifically exercise unverified-clinician paths pass
    `clinician_verified=False` (and `npi_match_status='none'` if they
    want the column to read as "never submitted").

    ``Clinician.org_id`` is NOT NULL. Callers persisting the returned row
    must pass ``org_id=<existing-org.id>`` in ``overrides`` (Org persisted
    separately via ``make_organization_row`` + ``session.add``), or use
    :func:`make_clinician_with_org` which builds the Org + Clinician in
    one call. Bare ORM constructors without an ``org_id`` will trip the
    NOT NULL constraint at flush time.
    """
    verified_defaults = {
        "clinician_verified": True,
        "npi_match_status": "matched",
    }
    return Clinician(
        owner_id=owner_id,
        **{**_CLINICIAN_DEFAULTS, **verified_defaults, **overrides},
    )


def make_organization_row(
    *,
    owner_id: UUID,
    name: str = "Acme Health",
    org_id: UUID | None = None,
) -> Organization:
    """Build an ``Organization`` ORM row. Assigns ``id`` eagerly so
    callers can pass ``org.id`` straight into a sibling
    ``make_clinician`` without an intermediate flush."""
    return Organization(
        id=org_id or uuid.uuid4(),
        name=name,
        owner_id=owner_id,
    )


def make_clinician_with_org(
    *,
    owner_id: UUID,
    practice_name: str = "Acme Health",
    org: Organization | None = None,
    **overrides: Any,
) -> Clinician:
    """Build a Clinician wired to an Organization. ``Organization.name``
    is the practice's display name; tests assert on ``clinician.org.name``.


    The Org is attached via ``clinician.org = org`` rather than just
    ``org_id`` so SQLAlchemy's default save-update cascade picks the
    Org up when the Clinician is added to a session — callers stay on
    the single-add ``session.add(clinician)`` shape.

    ``practice_name`` here names the *Organization* — the kwarg is
    kept under that name for call-site stability. Pass ``org=<instance>``
    when multiple Clinicians share an Org; the kwarg is ignored in that
    case (the existing Org's name wins)."""
    if org is None:
        org = make_organization_row(owner_id=owner_id, name=practice_name)
    clinician = make_clinician(
        owner_id=owner_id,
        org_id=org.id,
        **{k: v for k, v in overrides.items() if k != "practice_name"},
    )
    clinician.org = org
    return clinician


def make_clinician_licensure(
    *,
    clinician_id: UUID,
    **overrides: Any,
) -> ClinicianLicensure:
    """Build a `ClinicianLicensure` ORM row with CHECK-valid defaults.
    Pass `clinician_id=clinician.id` after the clinician has been flushed."""
    return ClinicianLicensure(
        clinician_id=clinician_id,
        **{**_CLINICIAN_LICENSURE_DEFAULTS, **overrides},
    )


def make_clinician_education(
    *,
    clinician_id: UUID,
    **overrides: Any,
) -> ClinicianEducation:
    """Build a `ClinicianEducation` ORM row. See
    :func:`make_clinician_licensure` for the FK contract."""
    return ClinicianEducation(
        clinician_id=clinician_id,
        **{**_CLINICIAN_EDUCATION_DEFAULTS, **overrides},
    )


def make_clinician_certification(
    *,
    clinician_id: UUID,
    **overrides: Any,
) -> ClinicianCertification:
    """Build a `ClinicianCertification` ORM row. See
    :func:`make_clinician_licensure` for the FK contract."""
    return ClinicianCertification(
        clinician_id=clinician_id,
        **{**_CLINICIAN_CERTIFICATION_DEFAULTS, **overrides},
    )


async def promote_to_admin(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    user_email: str,
) -> None:
    """Mutate a fixture-created user to is_superuser=True.

    Used by colocated tests that need an admin actor — the standard
    `authenticated_client` fixture creates a non-admin user, so tests that
    exercise admin-gated routes flip the bit on the existing user instead of
    reauthenticating as a different one.
    """
    async with db_test_session_manager() as session:
        async with session.begin():
            stmt = select(User).filter(User.email == user_email)
            result = await session.execute(stmt)
            user = result.scalars().first()
            assert user is not None, f"Test user {user_email} not found"
            user.is_superuser = True


def migrate_sqlite_file(db_path) -> None:
    """Build a file-backed SQLite DB at `db_path` by running every Alembic
    migration (`upgrade head`).

    The default test DB is in-memory via `metadata.create_all`, which
    skips anything that only exists in migrations — the observability
    SQL views (`src/domain/logic/admin_data/`) — and which Datasette
    can't open. Tests that need either build a file with this instead.
    """
    import os
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "config" / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
