"""Request/response schemas for `/posts` (kind-discriminated).

`Post` is polymorphic on `kind` (joined-table inheritance — see
`src/models/post.py`). Pydantic mirrors that with discriminated unions:
each kind has its own `*Create` / `*Read` / `*Update` schema, and
`PostCreate` / `PostRead` / `PostUpdate` are
`Annotated[Union[...], Field(discriminator="kind")]`. This gives FastAPI
a 422 with a clear pointer when an unknown `kind` arrives, and lets each
kind grow its own field set independently.

`kind` itself is server-set on creation (it's the discriminator). On
update the body must echo the same `kind` (the discriminator selects
which Update variant runs); the handler also enforces that the body's
`kind` matches the persisted post's kind, so a client can't repurpose a
post's identity via PATCH.

`client_referral` mirrors the multi-section intake form (Client Location,
Demographics, Description, Services, Insurance — see
`templates/posts/new.html`). `provider_availability` mirrors its own
multi-section form (Provider Information, Location, Availability,
Featured Services, Insurance). Per-section enums (`_State`,
`_Availability`, `_AgeGroup`, `_LanguagePreferred`, `_Service`,
`_Insurance`, `_DesiredTimeSlot`, `_TreatmentSetting`) are spelled out as
`Literal[...]` because Python doesn't permit `Literal[*tuple_var]`
syntax. A guardrail test
(`test_post.py::test_schema_literals_match_model_tuples`) keeps these in
lock-step with the source-of-truth tuples in `src/models/post.py` (which
feed the DB CHECK constraints).
"""

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- Per-section enums (mirror `src/models/post.py` tuples) --------------

_State = Literal[
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
]

_Availability = Literal["yes", "no", "please_contact"]

_AgeGroup = Literal[
    "children_0_5",
    "children_6_10",
    "preteens_11_13",
    "adolescents_14_18",
    "young_adults_19_24",
    "adults_25_64",
    "older_adults_65_plus",
]

_LanguagePreferred = Literal["no", "yes"]

_Service = Literal[
    "evaluation",
    "medication_management",
    "psychotherapy",
    "case_management",
    "allied_health",
]

_Insurance = Literal["in_network", "out_of_network", "in_and_out_of_network"]

_TreatmentSetting = Literal[
    "outpatient",
    "iop",
    "crisis_care",
    "php",
    "residential",
]

_DesiredTimeSlot = Literal[
    "monday_morning",
    "monday_afternoon",
    "monday_evening",
    "tuesday_morning",
    "tuesday_afternoon",
    "tuesday_evening",
    "wednesday_morning",
    "wednesday_afternoon",
    "wednesday_evening",
    "thursday_morning",
    "thursday_afternoon",
    "thursday_evening",
    "friday_morning",
    "friday_afternoon",
    "friday_evening",
    "saturday_morning",
    "saturday_afternoon",
    "saturday_evening",
    "sunday_morning",
    "sunday_afternoon",
    "sunday_evening",
]


# Exposed for the guardrail test in `test_post.py` — never used by route code.
_SCHEMA_ENUM_LITERALS = {
    "US_STATES": get_args(_State),
    "LOCATION_AVAILABILITY_OPTIONS": get_args(_Availability),
    "CLIENT_AGE_GROUPS": get_args(_AgeGroup),
    "LANGUAGE_PREFERRED_OPTIONS": get_args(_LanguagePreferred),
    "CLIENT_REFERRAL_SERVICES": get_args(_Service),
    "INSURANCE_OPTIONS": get_args(_Insurance),
    "TREATMENT_SETTINGS": get_args(_TreatmentSetting),
    "DESIRED_TIME_SLOTS": get_args(_DesiredTimeSlot),
}


# 5-digit US ZIP code; ZIP+4 is out of scope for now.
_ZIP_PATTERN = re.compile(r"^\d{5}$")


# --- Create --------------------------------------------------------------


class _PostCreateBase(BaseModel):
    """Shared config for per-kind create payloads."""

    model_config = ConfigDict(extra="forbid")


def _strip_required(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be empty")
    return v


def _strip_optional(v: str | None) -> str | None:
    """Strip surrounding whitespace; treat empty as None."""
    if v is None:
        return None
    v = v.strip()
    return v or None


def _validate_zip(v: str) -> str:
    v = v.strip()
    if not _ZIP_PATTERN.match(v):
        raise ValueError("must be a 5-digit ZIP code")
    return v


def _validate_unique_list(values: list[str], field_name: str) -> list[str]:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


def _validate_non_empty_list(values: list[str], field_name: str) -> list[str]:
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    return values


def _coerce_str_to_list(v):
    """HTMX `json-enc` serializes a single checked checkbox as a bare string
    (e.g. `"monday_morning"`) and 2+ checkboxes as an array. Coerce the
    single-string case to a 1-element list so the form's edge case
    round-trips into `list[Literal[...]]` cleanly."""
    if isinstance(v, str):
        return [v]
    return v


class ClientReferralCreate(_PostCreateBase):
    """Create payload for a client referral.

    Mirrors the multi-section intake form. All fields except
    `services_psychotherapy_modality` are required by the form spec; the
    multi-select `desired_times` and `services` accept an empty list when
    no checkbox is ticked.
    """

    kind: Literal["client_referral"]

    # Section 1: Client Location
    location_city: str
    location_state: _State
    location_zip: str
    location_in_person: _Availability
    location_virtual: _Availability
    desired_times: list[_DesiredTimeSlot] = Field(default_factory=list)

    # Section 2: Demographics
    client_dem_ages: _AgeGroup
    language_preferred: _LanguagePreferred

    # Section 3: Description
    description: str

    # Section 4: Services
    services: list[_Service] = Field(default_factory=list)
    services_psychotherapy_modality: str | None = None

    # Section 5: Insurance
    insurance: _Insurance

    @field_validator("location_city", "description")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_required(v)

    @field_validator("location_zip")
    @classmethod
    def _strip_zip(cls, v: str) -> str:
        return _validate_zip(v)

    @field_validator("services_psychotherapy_modality")
    @classmethod
    def _strip_modality(cls, v: str | None) -> str | None:
        return _strip_optional(v)

    @field_validator("desired_times", mode="before")
    @classmethod
    def _coerce_desired_times(cls, v):
        return _coerce_str_to_list(v)

    @field_validator("services", mode="before")
    @classmethod
    def _coerce_services(cls, v):
        return _coerce_str_to_list(v)

    @field_validator("desired_times")
    @classmethod
    def _unique_desired_times(cls, v: list[str]) -> list[str]:
        return _validate_unique_list(v, "desired_times")

    @field_validator("services")
    @classmethod
    def _unique_services(cls, v: list[str]) -> list[str]:
        return _validate_unique_list(v, "services")


class ProviderAvailabilityCreate(_PostCreateBase):
    """Create payload for a provider availability.

    Mirrors the multi-section intake form (Provider Information / Location /
    Availability / Featured Services / Insurance). All required fields per
    the form spec are required here; the multi-select `services` and
    `settings` must each have at least one selection. `desired_times`
    accepts an empty list (no slots ticked is allowed).
    """

    kind: Literal["provider_availability"]

    # Section 1: Provider Information
    practice_name: str
    available_providers: str

    # Section 2: Location
    location_city: str
    location_state: _State
    location_zip: str

    # Section 3: Availability
    in_person_sessions: _Availability
    virtual_sessions: _Availability
    desired_times: list[_DesiredTimeSlot] = Field(default_factory=list)

    # Section 4: Featured Services
    services: list[_Service]
    treatment_modality: str | None = None
    settings: list[_TreatmentSetting]
    client_focus: str
    age_group: _AgeGroup
    non_english_services: _LanguagePreferred = "no"

    # Section 5: Insurance
    payment_situation: _Insurance
    sliding_scale: bool
    cost: str | None = None

    @field_validator(
        "practice_name",
        "available_providers",
        "location_city",
        "client_focus",
    )
    @classmethod
    def _strip(cls, v: str) -> str:
        return _strip_required(v)

    @field_validator("location_zip")
    @classmethod
    def _strip_zip(cls, v: str) -> str:
        return _validate_zip(v)

    @field_validator("treatment_modality", "cost")
    @classmethod
    def _strip_optional_text(cls, v: str | None) -> str | None:
        return _strip_optional(v)

    @field_validator("desired_times", "services", "settings", mode="before")
    @classmethod
    def _coerce_lists(cls, v):
        return _coerce_str_to_list(v)

    @field_validator("desired_times")
    @classmethod
    def _unique_desired_times(cls, v: list[str]) -> list[str]:
        return _validate_unique_list(v, "desired_times")

    @field_validator("services")
    @classmethod
    def _services_non_empty_unique(cls, v: list[str]) -> list[str]:
        return _validate_unique_list(
            _validate_non_empty_list(v, "services"), "services"
        )

    @field_validator("settings")
    @classmethod
    def _settings_non_empty_unique(cls, v: list[str]) -> list[str]:
        return _validate_unique_list(
            _validate_non_empty_list(v, "settings"), "settings"
        )


PostCreate = Annotated[
    Union[ClientReferralCreate, ProviderAvailabilityCreate],
    Field(discriminator="kind"),
]


# --- Update --------------------------------------------------------------


class _PostUpdateBase(BaseModel):
    """Shared config for per-kind PATCH payloads."""

    model_config = ConfigDict(extra="forbid")


_CLIENT_REFERRAL_EDITABLE_FIELDS = (
    "location_city",
    "location_state",
    "location_zip",
    "location_in_person",
    "location_virtual",
    "desired_times",
    "client_dem_ages",
    "language_preferred",
    "description",
    "services",
    "services_psychotherapy_modality",
    "insurance",
)


class ClientReferralUpdate(_PostUpdateBase):
    """Partial update for a client_referral. All editable fields optional, but
    the schema rejects a no-op (no editable field set) at validation time."""

    kind: Literal["client_referral"]

    location_city: str | None = None
    location_state: _State | None = None
    location_zip: str | None = None
    location_in_person: _Availability | None = None
    location_virtual: _Availability | None = None
    desired_times: list[_DesiredTimeSlot] | None = None

    client_dem_ages: _AgeGroup | None = None
    language_preferred: _LanguagePreferred | None = None

    description: str | None = None

    services: list[_Service] | None = None
    services_psychotherapy_modality: str | None = None

    insurance: _Insurance | None = None

    @field_validator("location_city", "description")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _strip_required(v)

    @field_validator("location_zip")
    @classmethod
    def _strip_zip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_zip(v)

    @field_validator("services_psychotherapy_modality")
    @classmethod
    def _strip_modality(cls, v: str | None) -> str | None:
        return _strip_optional(v)

    @field_validator("desired_times", mode="before")
    @classmethod
    def _coerce_desired_times(cls, v):
        if v is None:
            return None
        return _coerce_str_to_list(v)

    @field_validator("services", mode="before")
    @classmethod
    def _coerce_services(cls, v):
        if v is None:
            return None
        return _coerce_str_to_list(v)

    @field_validator("desired_times")
    @classmethod
    def _unique_desired_times(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return _validate_unique_list(v, "desired_times")

    @field_validator("services")
    @classmethod
    def _unique_services(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return _validate_unique_list(v, "services")

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ClientReferralUpdate":
        if all(
            getattr(self, name) is None for name in _CLIENT_REFERRAL_EDITABLE_FIELDS
        ):
            raise ValueError(
                "at least one editable field must be provided: "
                + ", ".join(_CLIENT_REFERRAL_EDITABLE_FIELDS)
            )
        return self


_PROVIDER_AVAILABILITY_EDITABLE_FIELDS = (
    "practice_name",
    "available_providers",
    "location_city",
    "location_state",
    "location_zip",
    "in_person_sessions",
    "virtual_sessions",
    "desired_times",
    "services",
    "treatment_modality",
    "settings",
    "client_focus",
    "age_group",
    "non_english_services",
    "payment_situation",
    "sliding_scale",
    "cost",
)


class ProviderAvailabilityUpdate(_PostUpdateBase):
    """Partial update for a provider_availability. All editable fields
    optional, but the schema rejects a no-op (no editable field set) at
    validation time."""

    kind: Literal["provider_availability"]

    practice_name: str | None = None
    available_providers: str | None = None

    location_city: str | None = None
    location_state: _State | None = None
    location_zip: str | None = None

    in_person_sessions: _Availability | None = None
    virtual_sessions: _Availability | None = None
    desired_times: list[_DesiredTimeSlot] | None = None

    services: list[_Service] | None = None
    treatment_modality: str | None = None
    settings: list[_TreatmentSetting] | None = None
    client_focus: str | None = None
    age_group: _AgeGroup | None = None
    non_english_services: _LanguagePreferred | None = None

    payment_situation: _Insurance | None = None
    sliding_scale: bool | None = None
    cost: str | None = None

    @field_validator(
        "practice_name",
        "available_providers",
        "location_city",
        "client_focus",
    )
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _strip_required(v)

    @field_validator("location_zip")
    @classmethod
    def _strip_zip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_zip(v)

    @field_validator("treatment_modality", "cost")
    @classmethod
    def _strip_optional_text(cls, v: str | None) -> str | None:
        return _strip_optional(v)

    @field_validator("desired_times", "services", "settings", mode="before")
    @classmethod
    def _coerce_lists(cls, v):
        if v is None:
            return None
        return _coerce_str_to_list(v)

    @field_validator("desired_times")
    @classmethod
    def _unique_desired_times(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return _validate_unique_list(v, "desired_times")

    @field_validator("services")
    @classmethod
    def _services_non_empty_unique(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return _validate_unique_list(
            _validate_non_empty_list(v, "services"), "services"
        )

    @field_validator("settings")
    @classmethod
    def _settings_non_empty_unique(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return _validate_unique_list(
            _validate_non_empty_list(v, "settings"), "settings"
        )

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ProviderAvailabilityUpdate":
        if all(
            getattr(self, name) is None
            for name in _PROVIDER_AVAILABILITY_EDITABLE_FIELDS
        ):
            raise ValueError(
                "at least one editable field must be provided: "
                + ", ".join(_PROVIDER_AVAILABILITY_EDITABLE_FIELDS)
            )
        return self


PostUpdate = Annotated[
    Union[ClientReferralUpdate, ProviderAvailabilityUpdate],
    Field(discriminator="kind"),
]


# --- Read ----------------------------------------------------------------


class _PostReadBase(BaseModel):
    """Shared fields that surface on every kind."""

    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClientReferralRead(_PostReadBase):
    kind: Literal["client_referral"]

    location_city: str
    location_state: _State
    location_zip: str
    location_in_person: _Availability
    location_virtual: _Availability
    desired_times: list[_DesiredTimeSlot]

    client_dem_ages: _AgeGroup
    language_preferred: _LanguagePreferred

    description: str

    services: list[_Service]
    services_psychotherapy_modality: str | None

    insurance: _Insurance


class ProviderAvailabilityRead(_PostReadBase):
    kind: Literal["provider_availability"]

    practice_name: str
    available_providers: str

    location_city: str
    location_state: _State
    location_zip: str

    in_person_sessions: _Availability
    virtual_sessions: _Availability
    desired_times: list[_DesiredTimeSlot]

    services: list[_Service]
    treatment_modality: str | None
    settings: list[_TreatmentSetting]
    client_focus: str
    age_group: _AgeGroup
    non_english_services: _LanguagePreferred

    payment_situation: _Insurance
    sliding_scale: bool
    cost: str | None


PostRead = Annotated[
    Union[ClientReferralRead, ProviderAvailabilityRead],
    Field(discriminator="kind"),
]


# --- Audit ---------------------------------------------------------------


class PostAuditSnapshot(BaseModel):
    """Audit `before`/`after` projection for posts.

    Captures the user-meaningful fields a `Post` mutation can change. Per-kind
    fields default to `None` so a single snapshot shape covers every kind —
    Pydantic's `from_attributes` falls back to the default when a kind's
    instance doesn't expose a given attribute. Adding a field to this class
    flows through `_snapshot_post` automatically via `model_dump`.
    """

    kind: str
    owner_id: uuid.UUID

    # client_referral fields (Section 1: Client Location)
    location_city: str | None = None
    location_state: str | None = None
    location_zip: str | None = None
    location_in_person: str | None = None
    location_virtual: str | None = None
    desired_times: list[str] | None = None

    # client_referral fields (Section 2: Demographics)
    client_dem_ages: str | None = None
    language_preferred: str | None = None

    # client_referral fields (Section 3: Description)
    description: str | None = None

    # client_referral fields (Section 4: Services)
    services: list[str] | None = None
    services_psychotherapy_modality: str | None = None

    # client_referral fields (Section 5: Insurance)
    insurance: str | None = None

    # provider_availability fields (Section 1: Provider Information)
    practice_name: str | None = None
    available_providers: str | None = None

    # provider_availability fields (Section 3: Availability)
    in_person_sessions: str | None = None
    virtual_sessions: str | None = None

    # provider_availability fields (Section 4: Featured Services)
    treatment_modality: str | None = None
    settings: list[str] | None = None
    client_focus: str | None = None
    age_group: str | None = None
    non_english_services: str | None = None

    # provider_availability fields (Section 5: Insurance)
    payment_situation: str | None = None
    sliding_scale: bool | None = None
    cost: str | None = None

    model_config = ConfigDict(from_attributes=True)


__all__ = [
    "ClientReferralCreate",
    "ClientReferralRead",
    "ClientReferralUpdate",
    "PostAuditSnapshot",
    "PostCreate",
    "PostRead",
    "PostUpdate",
    "ProviderAvailabilityCreate",
    "ProviderAvailabilityRead",
    "ProviderAvailabilityUpdate",
]
