import uuid

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from .base import BaseModel

POST_KIND_CLIENT_REFERRAL = "client_referral"
POST_KIND_PROVIDER_AVAILABILITY = "provider_availability"
POST_KINDS = (POST_KIND_CLIENT_REFERRAL, POST_KIND_PROVIDER_AVAILABILITY)

# 50 states + District of Columbia (51 total).
US_STATES = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
)

LOCATION_AVAILABILITY_YES = "yes"
LOCATION_AVAILABILITY_NO = "no"
LOCATION_AVAILABILITY_PLEASE_CONTACT = "please_contact"
LOCATION_AVAILABILITY_OPTIONS = (
    LOCATION_AVAILABILITY_YES,
    LOCATION_AVAILABILITY_NO,
    LOCATION_AVAILABILITY_PLEASE_CONTACT,
)

CLIENT_AGE_GROUPS = (
    "children_0_5",
    "children_6_10",
    "preteens_11_13",
    "adolescents_14_18",
    "young_adults_19_24",
    "adults_25_64",
    "older_adults_65_plus",
)

LANGUAGE_PREFERRED_OPTIONS = ("no", "yes")

# Service taxonomy shared by both kinds: a `client_referral` lists the
# services it's seeking; a `provider_availability` lists the services it
# offers. Same set of labels in either direction.
CLIENT_REFERRAL_SERVICES = (
    "evaluation",
    "medication_management",
    "psychotherapy",
    "case_management",
    "allied_health",
)

INSURANCE_OPTIONS = (
    "in_network",
    "out_of_network",
    "in_and_out_of_network",
)

# Treatment-setting tokens for `provider_availability.settings` (multi-select).
TREATMENT_SETTINGS = (
    "outpatient",
    "iop",
    "crisis_care",
    "php",
    "residential",
)

# 7 days × 3 time-of-day slots = 21 valid `day_slot` strings. The form is a
# multi-select grid; selected slots are persisted as a JSON list of these
# tokens. Order in this tuple is the order rendered by the form.
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_TIME_SLOTS = ("morning", "afternoon", "evening")
DESIRED_TIME_SLOTS = tuple(f"{d}_{s}" for d in _DAYS for s in _TIME_SLOTS)


class Post(BaseModel):
    """Polymorphic base for all post kinds (joined-table inheritance).

    `posts` holds the shared header (owner, timestamps, kind discriminator);
    each kind has its own child table keyed by `id` FK to `posts.id`. A unified
    timeline (`GET /posts`) reads the parent table; per-kind fields load via
    `with_polymorphic` join or by querying the subclass directly.
    """

    __tablename__ = "posts"
    __mapper_args__ = {
        "polymorphic_identity": "post",
        "polymorphic_on": "kind",
    }

    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(Text, nullable=False)

    owner = relationship("User", lazy="joined")

    __table_args__ = (
        CheckConstraint(
            "kind IN ('{}')".format("','".join(POST_KINDS)),
            name="posts_kind_check",
        ),
    )


class ClientReferral(Post):
    """A request from a clinician for client placement / referral support.

    Carries **no PII** — fields describe what's needed in general terms only;
    the create form reminds users of this rule. Mirrors the multi-section
    intake form (Client Location, Demographics, Description, Services,
    Insurance) — the column groupings below match those sections.
    """

    __tablename__ = "client_referrals"
    __mapper_args__ = {"polymorphic_identity": POST_KIND_CLIENT_REFERRAL}

    id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
        default=uuid.uuid4,
    )

    # --- Section 1: Client Location ---
    location_city = Column(Text, nullable=False)
    location_state = Column(Text, nullable=False)
    location_zip = Column(Text, nullable=False)
    location_in_person = Column(Text, nullable=False)
    location_virtual = Column(Text, nullable=False)
    # JSON list of `<day>_<slot>` tokens drawn from `DESIRED_TIME_SLOTS`.
    # Empty list is allowed (nothing selected); membership/uniqueness is
    # enforced at the schema layer.
    desired_times = Column(JSON, nullable=False)

    # --- Section 2: Demographics ---
    client_dem_ages = Column(Text, nullable=False)
    language_preferred = Column(Text, nullable=False)

    # --- Section 3: Description ---
    description = Column(Text, nullable=False)

    # --- Section 4: Services ---
    # JSON list of service tokens drawn from `CLIENT_REFERRAL_SERVICES`.
    services = Column(JSON, nullable=False)
    # Free-text modality (e.g. "DBT") — only meaningful when `psychotherapy`
    # is one of the selected services; not enforced at the DB.
    services_psychotherapy_modality = Column(Text, nullable=True)

    # --- Section 5: Insurance ---
    insurance = Column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "location_state IN ('{}')".format("','".join(US_STATES)),
            name="client_referrals_location_state_check",
        ),
        CheckConstraint(
            "location_in_person IN ('{}')".format(
                "','".join(LOCATION_AVAILABILITY_OPTIONS)
            ),
            name="client_referrals_location_in_person_check",
        ),
        CheckConstraint(
            "location_virtual IN ('{}')".format(
                "','".join(LOCATION_AVAILABILITY_OPTIONS)
            ),
            name="client_referrals_location_virtual_check",
        ),
        CheckConstraint(
            "client_dem_ages IN ('{}')".format("','".join(CLIENT_AGE_GROUPS)),
            name="client_referrals_client_dem_ages_check",
        ),
        CheckConstraint(
            "language_preferred IN ('{}')".format(
                "','".join(LANGUAGE_PREFERRED_OPTIONS)
            ),
            name="client_referrals_language_preferred_check",
        ),
        CheckConstraint(
            "insurance IN ('{}')".format("','".join(INSURANCE_OPTIONS)),
            name="client_referrals_insurance_check",
        ),
    )


class ProviderAvailability(Post):
    """A provider listing their availability / open slots.

    Carries general availability metadata only — no client info. Mirrors the
    multi-section intake form (Provider Information, Location, Availability,
    Featured Services, Insurance); the column groupings below match those
    sections. Reuses the same allowed-value tuples as `ClientReferral`
    wherever the form vocabulary overlaps (states, availability, age groups,
    services, insurance, time slots).
    """

    __tablename__ = "provider_availabilities"
    __mapper_args__ = {"polymorphic_identity": POST_KIND_PROVIDER_AVAILABILITY}

    id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
        default=uuid.uuid4,
    )

    # --- Section 1: Provider Information ---
    practice_name = Column(Text, nullable=False)
    available_providers = Column(Text, nullable=False)

    # --- Section 2: Location ---
    location_city = Column(Text, nullable=False)
    location_state = Column(Text, nullable=False)
    location_zip = Column(Text, nullable=False)

    # --- Section 3: Availability ---
    in_person_sessions = Column(Text, nullable=False)
    virtual_sessions = Column(Text, nullable=False)
    # JSON list of `<day>_<slot>` tokens drawn from `DESIRED_TIME_SLOTS`.
    # Empty list is allowed (no slots ticked); membership / uniqueness are
    # enforced at the schema layer.
    desired_times = Column(JSON, nullable=False)

    # --- Section 4: Featured Services ---
    # JSON list of service tokens from `CLIENT_REFERRAL_SERVICES`. The form
    # spec requires at least one — enforced at the schema layer.
    services = Column(JSON, nullable=False)
    # Optional free-text modality (e.g. "DBT", "EMDR").
    treatment_modality = Column(Text, nullable=True)
    # JSON list of treatment-setting tokens from `TREATMENT_SETTINGS`. The
    # form spec requires at least one — enforced at the schema layer.
    settings = Column(JSON, nullable=False)
    client_focus = Column(Text, nullable=False)
    age_group = Column(Text, nullable=False)
    non_english_services = Column(Text, nullable=False)

    # --- Section 5: Insurance ---
    payment_situation = Column(Text, nullable=False)
    sliding_scale = Column(Boolean, nullable=False)
    cost = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "location_state IN ('{}')".format("','".join(US_STATES)),
            name="provider_availabilities_location_state_check",
        ),
        CheckConstraint(
            "in_person_sessions IN ('{}')".format(
                "','".join(LOCATION_AVAILABILITY_OPTIONS)
            ),
            name="provider_availabilities_in_person_sessions_check",
        ),
        CheckConstraint(
            "virtual_sessions IN ('{}')".format(
                "','".join(LOCATION_AVAILABILITY_OPTIONS)
            ),
            name="provider_availabilities_virtual_sessions_check",
        ),
        CheckConstraint(
            "age_group IN ('{}')".format("','".join(CLIENT_AGE_GROUPS)),
            name="provider_availabilities_age_group_check",
        ),
        CheckConstraint(
            "non_english_services IN ('{}')".format(
                "','".join(LANGUAGE_PREFERRED_OPTIONS)
            ),
            name="provider_availabilities_non_english_services_check",
        ),
        CheckConstraint(
            "payment_situation IN ('{}')".format("','".join(INSURANCE_OPTIONS)),
            name="provider_availabilities_payment_situation_check",
        ),
    )
