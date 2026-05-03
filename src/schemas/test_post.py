"""Schema tests for the kind-discriminated `/posts` payloads.

Pydantic validates `PostCreate` and `PostUpdate` as discriminated unions on
`kind`. These tests cover both kinds end-to-end on create and update,
their per-kind field sets, and the partial-update shape — including the
at-least-one-field rule, `extra="forbid"`, and the section-enum
guardrail that keeps the schema's `Literal[...]` lists in sync with the
source-of-truth tuples in `src/models/post.py`.
"""

import uuid

import pytest
from pydantic import TypeAdapter, ValidationError

from src.models.post import (
    CLIENT_AGE_GROUPS,
    CLIENT_REFERRAL_SERVICES,
    DESIRED_TIME_SLOTS,
    INSURANCE_OPTIONS,
    LANGUAGE_PREFERRED_OPTIONS,
    LOCATION_AVAILABILITY_OPTIONS,
    TREATMENT_SETTINGS,
    US_STATES,
)
from src.schemas.post import (
    _SCHEMA_ENUM_LITERALS,
    ClientReferralCreate,
    ClientReferralUpdate,
    PostCreate,
    PostUpdate,
    ProviderAvailabilityCreate,
    ProviderAvailabilityUpdate,
)

_post_create = TypeAdapter(PostCreate)
_post_update = TypeAdapter(PostUpdate)


# Minimal valid payload for `client_referral` — every required form field
# present, multi-selects empty, optional modality omitted.
_VALID_CLIENT_REFERRAL = {
    "kind": "client_referral",
    "location_city": "Northampton",
    "location_state": "MA",
    "location_zip": "01060",
    "location_in_person": "yes",
    "location_virtual": "please_contact",
    "desired_times": ["monday_morning", "wednesday_evening"],
    "client_dem_ages": "adults_25_64",
    "language_preferred": "no",
    "description": "looking for outpatient placement",
    "services": ["psychotherapy", "case_management"],
    "services_psychotherapy_modality": "DBT",
    "insurance": "in_network",
}


# Minimal valid payload for `provider_availability` — every required form
# field present, optional fields populated for round-trip coverage.
_VALID_PROVIDER_AVAILABILITY = {
    "kind": "provider_availability",
    "practice_name": "Bedlam Clinic",
    "available_providers": "Dr. A, Dr. B",
    "location_city": "Northampton",
    "location_state": "MA",
    "location_zip": "01060",
    "in_person_sessions": "yes",
    "virtual_sessions": "please_contact",
    "desired_times": ["monday_morning", "wednesday_evening"],
    "services": ["psychotherapy", "evaluation"],
    "treatment_modality": "DBT",
    "settings": ["outpatient", "iop"],
    "client_focus": "adults seeking trauma-informed care",
    "age_group": "adults_25_64",
    "non_english_services": "no",
    "payment_situation": "in_network",
    "sliding_scale": True,
    "cost": "$150 per session",
}


# --- Schema/model enum guardrail -----------------------------------------


def test_schema_literals_match_model_tuples():
    """Pydantic doesn't permit `Literal[*tuple_var]`, so the schema spells
    out each enum's allowed values. This guardrail keeps them aligned with
    the model-side tuples (which feed the DB CHECK constraints)."""
    assert _SCHEMA_ENUM_LITERALS["US_STATES"] == US_STATES
    assert (
        _SCHEMA_ENUM_LITERALS["LOCATION_AVAILABILITY_OPTIONS"]
        == LOCATION_AVAILABILITY_OPTIONS
    )
    assert _SCHEMA_ENUM_LITERALS["CLIENT_AGE_GROUPS"] == CLIENT_AGE_GROUPS
    assert (
        _SCHEMA_ENUM_LITERALS["LANGUAGE_PREFERRED_OPTIONS"]
        == LANGUAGE_PREFERRED_OPTIONS
    )
    assert _SCHEMA_ENUM_LITERALS["CLIENT_REFERRAL_SERVICES"] == CLIENT_REFERRAL_SERVICES
    assert _SCHEMA_ENUM_LITERALS["INSURANCE_OPTIONS"] == INSURANCE_OPTIONS
    assert _SCHEMA_ENUM_LITERALS["TREATMENT_SETTINGS"] == TREATMENT_SETTINGS
    assert _SCHEMA_ENUM_LITERALS["DESIRED_TIME_SLOTS"] == DESIRED_TIME_SLOTS


# --- Create dispatch -----------------------------------------------------


def test_post_create_dispatches_client_referral():
    parsed = _post_create.validate_python(_VALID_CLIENT_REFERRAL)
    assert isinstance(parsed, ClientReferralCreate)
    assert parsed.location_city == "Northampton"
    assert parsed.location_state == "MA"
    assert parsed.location_zip == "01060"
    assert parsed.desired_times == ["monday_morning", "wednesday_evening"]
    assert parsed.services == ["psychotherapy", "case_management"]
    assert parsed.services_psychotherapy_modality == "DBT"
    assert parsed.insurance == "in_network"


def test_post_create_dispatches_provider_availability():
    parsed = _post_create.validate_python(_VALID_PROVIDER_AVAILABILITY)
    assert isinstance(parsed, ProviderAvailabilityCreate)
    assert parsed.practice_name == "Bedlam Clinic"
    assert parsed.available_providers == "Dr. A, Dr. B"
    assert parsed.location_city == "Northampton"
    assert parsed.location_state == "MA"
    assert parsed.location_zip == "01060"
    assert parsed.in_person_sessions == "yes"
    assert parsed.virtual_sessions == "please_contact"
    assert parsed.desired_times == ["monday_morning", "wednesday_evening"]
    assert parsed.services == ["psychotherapy", "evaluation"]
    assert parsed.treatment_modality == "DBT"
    assert parsed.settings == ["outpatient", "iop"]
    assert parsed.client_focus == "adults seeking trauma-informed care"
    assert parsed.age_group == "adults_25_64"
    assert parsed.non_english_services == "no"
    assert parsed.payment_situation == "in_network"
    assert parsed.sliding_scale is True
    assert parsed.cost == "$150 per session"


def test_post_create_rejects_missing_kind():
    with pytest.raises(ValidationError):
        _post_create.validate_python({})


def test_post_create_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        _post_create.validate_python({"kind": "not_a_real_kind"})


# --- client_referral create per-section validation ----------------------


@pytest.mark.parametrize(
    "missing",
    [
        "location_city",
        "location_state",
        "location_zip",
        "location_in_person",
        "location_virtual",
        "client_dem_ages",
        "language_preferred",
        "description",
        "insurance",
    ],
)
def test_client_referral_create_requires_field(missing):
    payload = {**_VALID_CLIENT_REFERRAL}
    payload.pop(missing)
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


def test_client_referral_create_allows_empty_multiselects():
    """`desired_times` and `services` default to empty lists when no
    checkbox is ticked (json-enc omits unchecked checkboxes)."""
    payload = {**_VALID_CLIENT_REFERRAL}
    payload.pop("desired_times")
    payload.pop("services")
    payload.pop("services_psychotherapy_modality")
    parsed = _post_create.validate_python(payload)
    assert isinstance(parsed, ClientReferralCreate)
    assert parsed.desired_times == []
    assert parsed.services == []
    assert parsed.services_psychotherapy_modality is None


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("location_state", "ZZ"),
        ("location_in_person", "maybe"),
        ("location_virtual", "maybe"),
        ("client_dem_ages", "EVERYONE"),
        ("language_preferred", "fr"),
        ("insurance", "self_pay"),
    ],
)
def test_client_referral_create_rejects_bad_enum_values(field, bad_value):
    payload = {**_VALID_CLIENT_REFERRAL, field: bad_value}
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


@pytest.mark.parametrize("bad_zip", ["1234", "123456", "abcde", "01060-1234", ""])
def test_client_referral_create_rejects_bad_zip(bad_zip):
    payload = {**_VALID_CLIENT_REFERRAL, "location_zip": bad_zip}
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


def test_client_referral_create_strips_zip_whitespace():
    payload = {**_VALID_CLIENT_REFERRAL, "location_zip": "  01060  "}
    parsed = _post_create.validate_python(payload)
    assert parsed.location_zip == "01060"


@pytest.mark.parametrize("field", ["location_city", "description"])
def test_client_referral_create_rejects_whitespace_text(field):
    payload = {**_VALID_CLIENT_REFERRAL, field: "   "}
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


def test_client_referral_create_strips_text_whitespace():
    payload = {
        **_VALID_CLIENT_REFERRAL,
        "location_city": "  Northampton  ",
        "description": "  needs help  ",
    }
    parsed = _post_create.validate_python(payload)
    assert parsed.location_city == "Northampton"
    assert parsed.description == "needs help"


def test_client_referral_create_modality_empty_becomes_none():
    payload = {**_VALID_CLIENT_REFERRAL, "services_psychotherapy_modality": "   "}
    parsed = _post_create.validate_python(payload)
    assert parsed.services_psychotherapy_modality is None


@pytest.mark.parametrize(
    "field,raw,expected",
    [
        ("desired_times", "monday_morning", ["monday_morning"]),
        ("services", "psychotherapy", ["psychotherapy"]),
    ],
)
def test_client_referral_create_coerces_single_string_to_list(field, raw, expected):
    """HTMX `json-enc` sends a bare string when only one checkbox is ticked
    and an array when 2+ are ticked. The schema's BeforeValidator coerces
    the single-string case into a 1-element list."""
    payload = {**_VALID_CLIENT_REFERRAL, field: raw}
    parsed = _post_create.validate_python(payload)
    assert getattr(parsed, field) == expected


def test_client_referral_update_coerces_single_string_to_list():
    parsed = _post_update.validate_python(
        {"kind": "client_referral", "desired_times": "friday_evening"}
    )
    assert isinstance(parsed, ClientReferralUpdate)
    assert parsed.desired_times == ["friday_evening"]


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("desired_times", ["monday_zenith"]),
        ("services", ["telepathy"]),
    ],
)
def test_client_referral_create_rejects_bad_multiselect_value(field, bad_value):
    payload = {**_VALID_CLIENT_REFERRAL, field: bad_value}
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


@pytest.mark.parametrize(
    "field,duplicated",
    [
        ("desired_times", ["monday_morning", "monday_morning"]),
        ("services", ["psychotherapy", "psychotherapy"]),
    ],
)
def test_client_referral_create_rejects_duplicate_multiselect(field, duplicated):
    payload = {**_VALID_CLIENT_REFERRAL, field: duplicated}
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


def test_post_create_rejects_extra_fields():
    """`extra="forbid"` keeps stray fields out."""
    with pytest.raises(ValidationError):
        _post_create.validate_python({**_VALID_CLIENT_REFERRAL, "summary": "old"})


def test_post_create_rejects_owner_id():
    """owner_id is server-managed; clients sending it must be rejected."""
    with pytest.raises(ValidationError):
        _post_create.validate_python(
            {**_VALID_CLIENT_REFERRAL, "owner_id": str(uuid.uuid4())}
        )


# --- client_referral update ---------------------------------------------


@pytest.mark.parametrize(
    "patch_fields",
    [
        {"description": "new description"},
        {"location_city": "Boston"},
        {"location_state": "NY"},
        {"location_zip": "02108"},
        {"location_in_person": "no"},
        {"location_virtual": "yes"},
        {"desired_times": ["sunday_evening"]},
        {"client_dem_ages": "adolescents_14_18"},
        {"language_preferred": "yes"},
        {"services": ["evaluation"]},
        {"services_psychotherapy_modality": "EMDR"},
        {"insurance": "out_of_network"},
        {
            "description": "full update",
            "location_city": "Boston",
            "insurance": "in_and_out_of_network",
        },
    ],
)
def test_client_referral_update_accepts_partial(patch_fields):
    parsed = _post_update.validate_python({"kind": "client_referral", **patch_fields})
    assert isinstance(parsed, ClientReferralUpdate)


def test_client_referral_update_requires_at_least_one_field():
    with pytest.raises(ValidationError):
        _post_update.validate_python({"kind": "client_referral"})


def test_client_referral_update_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        _post_update.validate_python({"kind": "not_a_real_kind"})


def test_client_referral_update_rejects_extra_fields():
    with pytest.raises(ValidationError):
        _post_update.validate_python(
            {"kind": "client_referral", "description": "d", "evil": True}
        )


def test_client_referral_update_rejects_owner_id():
    with pytest.raises(ValidationError):
        _post_update.validate_python(
            {
                "kind": "client_referral",
                "description": "d",
                "owner_id": str(uuid.uuid4()),
            }
        )


def test_client_referral_update_rejects_whitespace_description():
    with pytest.raises(ValidationError):
        _post_update.validate_python({"kind": "client_referral", "description": "   "})


def test_client_referral_update_rejects_bad_zip():
    with pytest.raises(ValidationError):
        _post_update.validate_python({"kind": "client_referral", "location_zip": "12"})


def test_client_referral_update_rejects_bad_enum():
    with pytest.raises(ValidationError):
        _post_update.validate_python(
            {"kind": "client_referral", "insurance": "self_pay"}
        )


# --- provider_availability create per-section validation -----------------


@pytest.mark.parametrize(
    "missing",
    [
        "practice_name",
        "available_providers",
        "location_city",
        "location_state",
        "location_zip",
        "in_person_sessions",
        "virtual_sessions",
        "services",
        "settings",
        "client_focus",
        "age_group",
        "payment_situation",
        "sliding_scale",
    ],
)
def test_provider_availability_create_requires_field(missing):
    payload = {**_VALID_PROVIDER_AVAILABILITY}
    payload.pop(missing)
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


def test_provider_availability_create_omitting_desired_times_defaults_to_empty():
    """Form spec marks the 21-cell time grid optional — no slots ticked is
    allowed and arrives as a missing key from json-enc-arrays' empty-array
    branch only after we compose the payload, so the schema must default."""
    payload = {**_VALID_PROVIDER_AVAILABILITY}
    payload.pop("desired_times")
    parsed = _post_create.validate_python(payload)
    assert isinstance(parsed, ProviderAvailabilityCreate)
    assert parsed.desired_times == []


def test_provider_availability_create_omits_optional_fields():
    """treatment_modality, cost, and non_english_services are optional."""
    payload = {**_VALID_PROVIDER_AVAILABILITY}
    payload.pop("treatment_modality")
    payload.pop("cost")
    payload.pop("non_english_services")
    parsed = _post_create.validate_python(payload)
    assert isinstance(parsed, ProviderAvailabilityCreate)
    assert parsed.treatment_modality is None
    assert parsed.cost is None
    # non_english_services defaults to "no" when absent
    assert parsed.non_english_services == "no"


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("location_state", "ZZ"),
        ("in_person_sessions", "maybe"),
        ("virtual_sessions", "maybe"),
        ("age_group", "EVERYONE"),
        ("non_english_services", "fr"),
        ("payment_situation", "self_pay"),
    ],
)
def test_provider_availability_create_rejects_bad_enum_values(field, bad_value):
    payload = {**_VALID_PROVIDER_AVAILABILITY, field: bad_value}
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


@pytest.mark.parametrize("bad_zip", ["1234", "123456", "abcde", "01060-1234", ""])
def test_provider_availability_create_rejects_bad_zip(bad_zip):
    payload = {**_VALID_PROVIDER_AVAILABILITY, "location_zip": bad_zip}
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


@pytest.mark.parametrize(
    "field",
    [
        "practice_name",
        "available_providers",
        "location_city",
        "client_focus",
    ],
)
def test_provider_availability_create_rejects_whitespace_text(field):
    payload = {**_VALID_PROVIDER_AVAILABILITY, field: "   "}
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


def test_provider_availability_create_strips_whitespace():
    payload = {
        **_VALID_PROVIDER_AVAILABILITY,
        "practice_name": "  Bedlam Clinic  ",
        "available_providers": "  Dr. A, Dr. B  ",
        "location_city": "  Northampton  ",
        "client_focus": "  helping adults  ",
    }
    parsed = _post_create.validate_python(payload)
    assert parsed.practice_name == "Bedlam Clinic"
    assert parsed.available_providers == "Dr. A, Dr. B"
    assert parsed.location_city == "Northampton"
    assert parsed.client_focus == "helping adults"


@pytest.mark.parametrize("field", ["treatment_modality", "cost"])
def test_provider_availability_create_optional_text_empty_becomes_none(field):
    payload = {**_VALID_PROVIDER_AVAILABILITY, field: "   "}
    parsed = _post_create.validate_python(payload)
    assert getattr(parsed, field) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("true", True),
        ("false", False),
        (True, True),
        (False, False),
    ],
)
def test_provider_availability_create_coerces_sliding_scale_bool(raw, expected):
    """Form payloads carry strings; Pydantic coerces them to bool."""
    payload = {**_VALID_PROVIDER_AVAILABILITY, "sliding_scale": raw}
    parsed = _post_create.validate_python(payload)
    assert parsed.sliding_scale is expected


@pytest.mark.parametrize(
    "field,raw,expected",
    [
        ("desired_times", "monday_morning", ["monday_morning"]),
        ("services", "psychotherapy", ["psychotherapy"]),
        ("settings", "outpatient", ["outpatient"]),
    ],
)
def test_provider_availability_create_coerces_single_string_to_list(
    field, raw, expected
):
    """HTMX `json-enc` sends a bare string when only one checkbox is ticked.
    The schema's BeforeValidator coerces it to a 1-element list."""
    payload = {**_VALID_PROVIDER_AVAILABILITY, field: raw}
    parsed = _post_create.validate_python(payload)
    assert getattr(parsed, field) == expected


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("desired_times", ["monday_zenith"]),
        ("services", ["telepathy"]),
        ("settings", ["full_moon"]),
    ],
)
def test_provider_availability_create_rejects_bad_multiselect_value(field, bad_value):
    payload = {**_VALID_PROVIDER_AVAILABILITY, field: bad_value}
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


@pytest.mark.parametrize(
    "field,duplicated",
    [
        ("desired_times", ["monday_morning", "monday_morning"]),
        ("services", ["psychotherapy", "psychotherapy"]),
        ("settings", ["outpatient", "outpatient"]),
    ],
)
def test_provider_availability_create_rejects_duplicate_multiselect(field, duplicated):
    payload = {**_VALID_PROVIDER_AVAILABILITY, field: duplicated}
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


@pytest.mark.parametrize("field", ["services", "settings"])
def test_provider_availability_create_rejects_empty_required_multiselect(field):
    """The form spec marks both services and settings as 'at least one
    required'; the schema enforces a non-empty list."""
    payload = {**_VALID_PROVIDER_AVAILABILITY, field: []}
    with pytest.raises(ValidationError):
        _post_create.validate_python(payload)


def test_provider_availability_create_rejects_extra_fields():
    with pytest.raises(ValidationError):
        _post_create.validate_python(
            {**_VALID_PROVIDER_AVAILABILITY, "specialty": "psychiatry"}
        )


def test_provider_availability_create_rejects_owner_id():
    with pytest.raises(ValidationError):
        _post_create.validate_python(
            {**_VALID_PROVIDER_AVAILABILITY, "owner_id": str(uuid.uuid4())}
        )


# --- provider_availability update ---------------------------------------


@pytest.mark.parametrize(
    "patch_fields",
    [
        {"practice_name": "new"},
        {"available_providers": "new"},
        {"location_city": "Boston"},
        {"location_state": "NY"},
        {"location_zip": "02108"},
        {"in_person_sessions": "no"},
        {"virtual_sessions": "yes"},
        {"desired_times": ["sunday_evening"]},
        {"services": ["evaluation"]},
        {"treatment_modality": "EMDR"},
        {"settings": ["residential"]},
        {"client_focus": "young adults"},
        {"age_group": "adolescents_14_18"},
        {"non_english_services": "yes"},
        {"payment_situation": "out_of_network"},
        {"sliding_scale": False},
        {"cost": "$200/session"},
        {"practice_name": "p", "settings": ["php"], "sliding_scale": True},
    ],
)
def test_provider_availability_update_accepts_partial(patch_fields):
    parsed = _post_update.validate_python(
        {"kind": "provider_availability", **patch_fields}
    )
    assert isinstance(parsed, ProviderAvailabilityUpdate)


def test_provider_availability_update_requires_at_least_one_field():
    with pytest.raises(ValidationError):
        _post_update.validate_python({"kind": "provider_availability"})


def test_provider_availability_update_rejects_extra_fields():
    with pytest.raises(ValidationError):
        _post_update.validate_python(
            {"kind": "provider_availability", "practice_name": "p", "evil": True}
        )


def test_provider_availability_update_rejects_owner_id():
    with pytest.raises(ValidationError):
        _post_update.validate_python(
            {
                "kind": "provider_availability",
                "practice_name": "p",
                "owner_id": str(uuid.uuid4()),
            }
        )


@pytest.mark.parametrize(
    "field",
    ["practice_name", "available_providers", "location_city", "client_focus"],
)
def test_provider_availability_update_rejects_whitespace_text(field):
    with pytest.raises(ValidationError):
        _post_update.validate_python({"kind": "provider_availability", field: "   "})


def test_provider_availability_update_rejects_bad_zip():
    with pytest.raises(ValidationError):
        _post_update.validate_python(
            {"kind": "provider_availability", "location_zip": "12"}
        )


def test_provider_availability_update_rejects_bad_enum():
    with pytest.raises(ValidationError):
        _post_update.validate_python(
            {"kind": "provider_availability", "payment_situation": "self_pay"}
        )


@pytest.mark.parametrize("field", ["services", "settings"])
def test_provider_availability_update_rejects_empty_required_multiselect(field):
    with pytest.raises(ValidationError):
        _post_update.validate_python({"kind": "provider_availability", field: []})


def test_provider_availability_update_coerces_single_string_to_list():
    parsed = _post_update.validate_python(
        {"kind": "provider_availability", "settings": "outpatient"}
    )
    assert isinstance(parsed, ProviderAvailabilityUpdate)
    assert parsed.settings == ["outpatient"]
