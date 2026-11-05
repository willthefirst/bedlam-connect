"""Tests for the post view helpers (`view.py`)."""

from types import SimpleNamespace

import pytest

from src.domain.logic.posts.view import (
    _LIST_PASSTHROUGH,
    _SCALAR_PASSTHROUGH,
    affiliation_options,
    insurance_posture_for_post,
    location_summary,
    post_card_view,
    post_feed_headline,
    post_row_summary,
    program_options,
    referral_headline,
    service_labels,
)


def _cr_post(
    *,
    accepts_private_pay: bool = False,
    insurance_carriers: list[str] | None = None,
):
    return SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            accepts_private_pay=accepts_private_pay,
            insurance_carriers=insurance_carriers or [],
        ),
    )


def _pa_post(*, cost=None, **affiliation_attrs):
    """Posture stub. Insurance posture for an opening reads the
    affiliation's in-network/OON/sliding-scale, plus the opening's own
    per-announcement ``cost`` (which moved onto the opening detail row)."""
    affiliation_attrs.setdefault("in_network_carriers", [])
    affiliation_attrs.setdefault("accepts_out_of_network", False)
    affiliation_attrs.setdefault("sliding_scale", False)
    return SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            cost=cost,
            clinician_affiliation=SimpleNamespace(**affiliation_attrs),
        ),
    )


def test_cr_posture_prefers_in_network():
    """In-network is the highest-signal posture, read off carrier presence
    (a non-empty `insurance_carriers` list); it wins even when private pay
    is also accepted."""
    post = _cr_post(insurance_carriers=["cigna"], accepts_private_pay=True)
    assert insurance_posture_for_post(post) == "in_network"


def test_cr_posture_falls_back_to_private_pay_then_none():
    """Priority order: in-network > private-pay > None (none set). The
    OON-superbill branch was removed when the superbill column was
    dropped from the referral schema."""
    assert insurance_posture_for_post(_cr_post(accepts_private_pay=True)) == "self_pay"
    # Both booleans false → the referral states no preference; the
    # helper returns None and the row/facts macros omit the chunk.
    assert insurance_posture_for_post(_cr_post()) is None


def test_pa_posture_prefers_in_network_when_set():
    """In-network is the highest-signal posture; show it even when the
    clinician also accepts out-of-network or offers sliding scale."""
    post = _pa_post(
        in_network_carriers=["aetna"],
        accepts_out_of_network=True,
        sliding_scale=True,
    )
    assert insurance_posture_for_post(post) == "in_network"


def test_pa_posture_falls_back_to_oon_then_self_pay_then_none():
    assert (
        insurance_posture_for_post(_pa_post(accepts_out_of_network=True))
        == "out_of_network"
    )
    assert insurance_posture_for_post(_pa_post(sliding_scale=True)) == "self_pay"
    assert insurance_posture_for_post(_pa_post(cost="$150/session")) == "self_pay"
    # No flags set at all → the post offers no insurance signal; the
    # helper returns None and the facts macro omits the chunk.
    assert insurance_posture_for_post(_pa_post()) is None


def test_posture_returns_none_for_unknown_kind():
    """An unregistered kind has no detail row; the helper returns None
    and the row macro omits the insurance chunk."""
    post = SimpleNamespace(kind="mystery")
    assert insurance_posture_for_post(post) is None


def test_posture_returns_none_when_detail_missing():
    post = SimpleNamespace(kind="referral", referral_detail=None)
    assert insurance_posture_for_post(post) is None


# --- referral_headline -------------------------------------------


@pytest.mark.parametrize(
    "age,expected",
    [
        ("adults_25_64", "Adult (25–64)"),
        ("adolescents_14_18", "Adolescent (14–18)"),
        ("young_adults_19_24", "Young adult (19–24)"),
        ("older_adults_65_plus", "Older adult (65+)"),
    ],
)
def test_referral_headline_composes_age(age, expected):
    """`gender` was removed from the referral schema; the headline is
    now `"<noun> (<range>)"`."""
    detail = SimpleNamespace(age_groups=[age])
    assert referral_headline(detail) == expected


def test_referral_headline_appends_pronouns_after_age_with_middot():
    """Age + range lead; pronouns follow after a mid-dot (not a comma, so
    a multi-pronoun list stays unambiguous)."""
    detail = SimpleNamespace(age_groups=["adults_25_64"], pronouns=["she_her"])
    assert referral_headline(detail) == "Adult (25–64) · she/her"


def test_referral_headline_caps_pronouns_at_two():
    detail = SimpleNamespace(
        age_groups=["adults_25_64"],
        pronouns=["she_her", "they_them", "he_him"],
    )
    assert referral_headline(detail) == "Adult (25–64) · she/her, they/them"


def test_referral_headline_uses_first_age_group_only():
    """CR posts describe one client; the schema allows multi age_groups
    for forward-compat but the headline picks the first value so the
    title stays a single "<noun> (<range>)" phrase."""
    detail = SimpleNamespace(
        age_groups=["adolescents_14_18", "adults_25_64"],
    )
    assert referral_headline(detail) == "Adolescent (14–18)"


def test_referral_headline_falls_back_when_age_groups_empty():
    """Defensive — schema requires min-1, but the helper degrades
    gracefully if a future code path hands us an empty list."""
    detail = SimpleNamespace(age_groups=[])
    assert referral_headline(detail) == "Client Referral"


# --- post_card_view -----------------------------------------------------
#
# The view-model collapses three kind-specific detail shapes (CR has its
# own location + a scalar gender; PA reads location + insurance off the
# linked ClinicianAffiliation; program reads identity off the linked
# Program) into one flat dict that templates iterate over. Tests below build a stub
# post per kind and pin the dict's shape end-to-end. Templates are
# tested separately at the route level.


_CR_REFERRING_CLINICIAN_DEFAULTS = dict(
    id="ref-clin-1",
    first_name="Carlos",
    last_name="Rivera",
)
_CR_REFERRING_AFFILIATION_DEFAULTS = dict(
    location_city="Cambridge",
    location_state="MA",
    location_zip="02139",
    org=SimpleNamespace(id="org-ref", name="River Health"),
)
# Sentinel for `_make_cr_post` to distinguish "no kwarg passed → apply
# defaults" from "kwarg explicitly None → clear the relation". Plain
# ``None`` can't carry both meanings.
_UNSET = object()


def _make_cr_post(
    *,
    referring_clinician_attrs=_UNSET,
    referring_affiliation_attrs=_UNSET,
    **detail_overrides,
):
    """Realistic CR stub. Defaults populate every field with a sensible
    value so tests can override only what they care about.

    Referring-clinician shape mirrors the model — a `Clinician` with
    `first_name`/`last_name`/`id`, and a `ClinicianAffiliation` with
    `location_*` + `org`. Pass ``referring_clinician_attrs=None`` (or
    ``referring_affiliation_attrs=None``) to clear that relation —
    e.g. legacy pre-#1454 rows or a sole-prop clinician with no
    affiliation. A dict merges into the defaults."""
    defaults = dict(
        location_city="Brooklyn",
        location_state="NY",
        session_format=["in_person"],
        age_groups=["adults_25_64"],
        languages=["en", "es"],
        description="Looking for a therapist who takes BCBS.",
        services=["psychotherapy", "medication_management"],
        accepts_private_pay=False,
        insurance_carriers=["anthem_bcbs"],
    )
    defaults.update(detail_overrides)
    if referring_clinician_attrs is _UNSET:
        rc = SimpleNamespace(**_CR_REFERRING_CLINICIAN_DEFAULTS)
    elif referring_clinician_attrs is None:
        rc = None
    else:
        rc = SimpleNamespace(
            **{**_CR_REFERRING_CLINICIAN_DEFAULTS, **referring_clinician_attrs}
        )
    if referring_affiliation_attrs is _UNSET:
        aff = SimpleNamespace(**_CR_REFERRING_AFFILIATION_DEFAULTS)
    elif referring_affiliation_attrs is None:
        aff = None
    else:
        aff = SimpleNamespace(
            **{**_CR_REFERRING_AFFILIATION_DEFAULTS, **referring_affiliation_attrs}
        )
    defaults["referring_clinician"] = rc
    defaults["clinician_affiliation"] = aff
    return SimpleNamespace(
        kind="referral",
        owner=SimpleNamespace(
            clinicians=[SimpleNamespace(first_name="Carlos", last_name="Rivera")]
        ),
        referral_detail=SimpleNamespace(**defaults),
    )


# After the opening remodel the announcement profile is self-describing —
# `services` / `age_groups` / `genders` / `session_format` / `cost` /
# `services_other_text` live on the OpeningDetail row itself. Only
# steady-state CONTEXT (org, location, insurance, how-to-refer) reads from
# the linked affiliation; `languages` is person-level on the clinician.
_PA_OPENING_PROFILE_DEFAULTS = dict(
    services=["psychotherapy"],
    age_groups=["adults_25_64"],
    genders=["female", "non_binary"],
    session_format=["in_person", "virtual"],
    services_other_text=None,
    cost="$150/session",
)
_PA_AFFILIATION_CONTEXT_DEFAULTS = dict(
    website="https://example.com",
    referral_instructions="Email intake@example.com",
    # Practice-role context — org, location, insurance — lives on the
    # affiliation the opening announces, never on the clinician (whose
    # same-named attributes are primary-affiliation proxies). No ZIP, no
    # session-availability columns: delivery format is per-announcement now.
    org=SimpleNamespace(id="org-1", name="Acme Counseling"),
    location_city="Brooklyn",
    location_state="NY",
    in_network_carriers=["aetna"],
    accepts_out_of_network=False,
    sliding_scale=True,
)
_PA_CLINICIAN_PERSON_DEFAULTS = dict(
    languages=["en"],
)
_PA_OPENING_CORE_DEFAULTS = dict(
    description="Accepting new clients.",
    schedule_text="Mon-Wed 9-5",
)

# Legacy alias kept for the older session-availability tests that still
# pass `in_person_sessions` / `virtual_sessions` overrides — these now
# map to the opening's `session_format` (see `_make_pa_post`).
_PA_SESSION_AVAILABILITY_KEYS = {"in_person_sessions", "virtual_sessions"}


def _make_pa_post(*, clinician_attrs=None, **overrides):
    """Realistic PA stub. ``overrides`` can target the announcement core
    (``description`` / ``schedule_text``), the self-describing announcement
    profile (``services`` / ``age_groups`` / ``genders`` /
    ``session_format`` / ``cost`` — all on the OpeningDetail row), the
    steady-state affiliation context, or ``languages`` (on the clinician).

    For call-site stability, the legacy ``in_person_sessions`` /
    ``virtual_sessions`` overrides are still accepted and folded into the
    opening's ``session_format`` list (``"yes"`` → membership)."""
    p = dict(
        id="prov-1",
        first_name="Jane",
        last_name="Smith",
        **_PA_CLINICIAN_PERSON_DEFAULTS,
    )
    aff = dict(**_PA_AFFILIATION_CONTEXT_DEFAULTS)
    detail = dict(**_PA_OPENING_PROFILE_DEFAULTS)
    core = dict(**_PA_OPENING_CORE_DEFAULTS)
    # Legacy session-availability overrides → session_format membership.
    if _PA_SESSION_AVAILABILITY_KEYS & overrides.keys():
        fmt = []
        in_person = overrides.pop("in_person_sessions", None)
        virtual = overrides.pop("virtual_sessions", None)
        if in_person == "yes":
            fmt.append("in_person")
        if virtual == "yes":
            fmt.append("virtual")
        detail["session_format"] = fmt
    for k, v in overrides.items():
        if k in _PA_OPENING_PROFILE_DEFAULTS:
            detail[k] = v
        elif k in _PA_AFFILIATION_CONTEXT_DEFAULTS:
            aff[k] = v
        elif k in _PA_CLINICIAN_PERSON_DEFAULTS:
            p[k] = v
        else:
            core[k] = v
    if clinician_attrs:
        p.update(clinician_attrs)
    return SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            clinician=SimpleNamespace(**p),
            clinician_affiliation=SimpleNamespace(**aff),
            **detail,
            **core,
        ),
    )


# After the program-intake remodel the intake is self-describing too —
# `services` / `services_other_text` / `age_groups` / `genders` / `cost`
# live on the `IntakeDetail` row itself (on the same `ReferralService`
# vocab the referral + opening sides use). Only steady-state context —
# the Program name / `state_preference` / `languages` / `website` /
# `referral_instructions` / owning org — stays on the linked `Program`.
# `settings` / `modalities` were dropped entirely (no kind models them).
_PROGRAM_INTAKE_PROFILE_DEFAULTS = dict(
    services=["medication_management"],
    services_other_text=None,
    age_groups=["adolescents_14_18"],
    genders=[],
    cost=None,
)
_PROGRAM_STEADY_STATE_DEFAULTS = dict(
    languages=["en"],
    website="https://riseiop.example.com",
    referral_instructions=None,
)
_PROGRAM_INTAKE_CORE_DEFAULTS = dict(
    description="Intake cohort opens June 1.",
    schedule_text="M-F 9-3",
)


def _make_program_post(*, program_attrs=None, **overrides):
    """Realistic intake stub. ``overrides`` can target the announcement
    core (``description`` / ``schedule_text``), the self-describing intake
    profile (``services`` / ``age_groups`` / ``genders`` / ``cost`` — all
    on the IntakeDetail row), or the steady-state Program context
    (``languages`` / ``website`` / ``referral_instructions``)."""
    p = dict(
        id="prog-1",
        name="RISE IOP",
        state_preference="CT",
        organization=SimpleNamespace(id="org-h", name="Acme Health"),
        **_PROGRAM_STEADY_STATE_DEFAULTS,
    )
    detail = dict(**_PROGRAM_INTAKE_PROFILE_DEFAULTS)
    core = dict(**_PROGRAM_INTAKE_CORE_DEFAULTS)
    for k, v in overrides.items():
        if k in _PROGRAM_INTAKE_PROFILE_DEFAULTS:
            detail[k] = v
        elif k in _PROGRAM_STEADY_STATE_DEFAULTS:
            p[k] = v
        else:
            core[k] = v
    if program_attrs:
        p.update(program_attrs)
    return SimpleNamespace(
        kind="program_intake",
        intake_detail=SimpleNamespace(
            program=SimpleNamespace(**p),
            **detail,
            **core,
        ),
    )


# --- post_card_view: referral ------------------------------------


def test_view_cr_basics():
    """Per-kind discriminators map to the unified verb vocabulary the
    card's left-edge color and `_services_block` H4 both read from."""
    v = post_card_view(_make_cr_post())
    assert v["kind"] == "referral"
    assert v["kind_verb"] == "Seeking"


def test_view_cr_headline_from_age():
    v = post_card_view(_make_cr_post(age_groups=["adults_25_64"]))
    assert v["headline"] == "Adult (25–64)"


def test_view_cr_header_state_is_none_state_lives_in_location_chunk():
    """CR shows state in the demographics column (`location_chunk`),
    not in the header line — the headline already carries the
    identity. Pin `header_state` is intentionally None for CR."""
    v = post_card_view(_make_cr_post())
    assert v["header_state"] is None
    # Referrals carry (city, state) only — no ZIP on the referral side.
    assert v["location_chunk"] == {"city": "Brooklyn", "state": "NY", "zip": None}


def test_view_cr_in_person_and_virtual_derive_from_session_format():
    """The referral side stores `session_format` as a list[str] subset
    of {in_person, virtual}. The cross-kind list/detail templates still
    read `view.in_person` / `view.virtual`, so the view derives them
    from list membership."""
    v = post_card_view(_make_cr_post(session_format=["in_person"]))
    assert v["session_format"] == ["in_person"]
    assert v["in_person"] == "yes"
    assert v["virtual"] == "no"

    v = post_card_view(_make_cr_post(session_format=["virtual"]))
    assert (v["in_person"], v["virtual"]) == ("no", "yes")

    v = post_card_view(_make_cr_post(session_format=["in_person", "virtual"]))
    assert (v["in_person"], v["virtual"]) == ("yes", "yes")

    v = post_card_view(_make_cr_post(session_format=[]))
    assert (v["in_person"], v["virtual"]) == (None, None)


def test_view_cr_settings_always_empty():
    """CR has no `settings` field on its detail row; the view-model
    returns an empty list so templates can iterate uniformly."""
    v = post_card_view(_make_cr_post())
    assert v["settings"] == []


def test_view_cr_full_address_composes_city_state():
    """Referrals carry (city, state) only — no ZIP."""
    v = post_card_view(_make_cr_post())
    assert v["full_address"] == "Brooklyn, NY"


def test_view_cr_cr_only_fields_set_pa_only_fields_none():
    """CR populates `accepts_private_pay` + `insurance_carriers` (the
    carrier list is the in-network signal — no boolean); the link keys
    (PA/program identity) stay at their None defaults."""
    v = post_card_view(_make_cr_post())
    assert v["accepts_private_pay"] is False
    assert v["insurance_carriers"] == ["anthem_bcbs"]
    assert v["practice_link"] is None
    assert v["program_link"] is None
    assert v["organization_link"] is None


# --- post_card_view: opening ------------------------------


def test_view_pa_basics():
    v = post_card_view(_make_pa_post())
    assert v["kind"] == "clinician_opening"
    assert v["kind_verb"] == "Providing"


def test_view_pa_headline_is_org_name_state_from_clinician():
    """PA's identity is the practice — `clinician.org.name`. State
    surfaces via `location_chunk` (the demographics-column icon-only
    row), matching the CR treatment so referral + opening cards
    consistently locate their location in the same place. The header
    line stays uncluttered for both kinds."""
    v = post_card_view(_make_pa_post())
    assert v["headline"] == "Acme Counseling"
    assert v["header_state"] is None
    # Opening location is city/area + state, no ZIP.
    assert v["location_chunk"] == {"city": "Brooklyn", "state": "NY", "zip": None}


def test_view_pa_in_person_virtual_derive_from_session_format():
    """PA's delivery format is per-announcement now (the opening's own
    `session_format`); the cross-kind `in_person`/`virtual` view keys are
    back-derived from list membership, exactly like the referral side."""
    v = post_card_view(_make_pa_post(session_format=["virtual"]))
    assert v["in_person"] == "no"
    assert v["virtual"] == "yes"

    v = post_card_view(_make_pa_post(session_format=["in_person"]))
    assert v["in_person"] == "yes"
    assert v["virtual"] == "no"

    v = post_card_view(_make_pa_post(session_format=[]))
    assert v["in_person"] is None
    assert v["virtual"] is None


def test_view_pa_practice_link_carries_id_and_org_name():
    v = post_card_view(_make_pa_post())
    assert v["practice_link"] == {"id": "prov-1", "name": "Acme Counseling"}


def test_view_pa_organization_link_carries_org_id_and_name():
    """Opening's org link reads through `clinician_affiliation.org` so
    the detail page's `Organization` row is a one-click jump to the
    owning org."""
    v = post_card_view(_make_pa_post())
    assert v["organization_link"] == {"id": "org-1", "name": "Acme Counseling"}


def test_view_pa_full_address_from_affiliation():
    v = post_card_view(_make_pa_post())
    assert v["full_address"] == "Brooklyn, NY"


def test_view_pa_feed_insurance_fields_from_affiliation():
    """The feed-row meta strip reads these three keys for the opening
    insurance chunk; they come from the linked affiliation. `cost` is now
    a view key too — it moved onto the opening detail row (per-announcement)
    and is read off it."""
    v = post_card_view(_make_pa_post())
    assert v["in_network_carriers"] == ["aetna"]
    assert v["accepts_out_of_network"] is False
    assert v["sliding_scale"] is True
    assert v["cost"] == "$150/session"


def test_view_pa_settings_empty_genders_from_detail():
    """Openings dropped `settings` (always `[]` now); `genders` is part
    of the opening's self-describing profile, read off the detail row."""
    v = post_card_view(_make_pa_post())
    assert v["settings"] == []
    assert v["genders"] == ["female", "non_binary"]


def test_view_pa_location_chunk_from_affiliation():
    """PA's `location_chunk` reads city/state from the linked
    ClinicianAffiliation (no ZIP — the affiliation models city/area +
    state only). Detail page gets the same string via `full_address`."""
    v = post_card_view(_make_pa_post())
    assert v["location_chunk"] == {"city": "Brooklyn", "state": "NY", "zip": None}
    assert v["full_address"] == "Brooklyn, NY"


def test_view_pa_no_location_chunk_when_clinician_missing():
    """Defensive — a PA stub without a `clinician` relationship returns
    `location_chunk=None` instead of crashing. Mirrors the same
    defensive path the existing PA-missing-clinician test covers for
    other clinician-derived fields."""
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            clinician=None,
            clinician_affiliation=None,
            description=None,
            schedule_text=None,
        ),
    )
    v = post_card_view(post)
    assert v["location_chunk"] is None


# --- post_card_view: intake -------------------------------


def test_view_program_basics():
    v = post_card_view(_make_program_post())
    assert v["kind"] == "program_intake"
    assert v["kind_verb"] == "Providing"


def test_view_program_headline_is_program_name_state_from_program():
    v = post_card_view(_make_program_post())
    assert v["headline"] == "RISE IOP"
    assert v["header_state"] == "CT"


def test_view_program_link_carries_id_and_name():
    v = post_card_view(_make_program_post())
    assert v["program_link"] == {"id": "prog-1", "name": "RISE IOP"}


def test_view_program_organization_link_carries_org_id_and_name():
    """Detail page surfaces the owning Org as a clickable link below
    the Program link — the view-model exposes `{id, name}` so the
    template renders an `<a>` (mirrors `practice_link` /
    `program_link`); a one-click jump to `/organizations/{id}`."""
    v = post_card_view(_make_program_post())
    assert v["organization_link"] == {"id": "org-h", "name": "Acme Health"}


def test_view_program_no_in_person_virtual_no_insurance_no_address():
    """Program-availability has no in-person/virtual posture (the
    Program doesn't track session format today), no insurance posture
    (insurance lives on Clinician, not Program), and no location of
    its own (the linked Program's `state_preference` surfaces via
    `header_state` instead)."""
    v = post_card_view(_make_program_post())
    assert v["in_person"] is None
    assert v["virtual"] is None
    assert v["insurance_posture"] is None
    assert v["full_address"] is None
    assert v["location_chunk"] is None


# --- post_card_view: modalities -----------------------------------------
#
# `modalities` was removed from every detail row and steady-state home
# (the services collapsed onto the single `ReferralService` vocab across
# all three kinds). The view-model key stays `[]` for every kind.


def test_view_pa_modalities_always_empty():
    """Openings carry no `modalities` axis any more — the view-model key
    stays `[]` for every opening."""
    v = post_card_view(_make_pa_post())
    assert v["modalities"] == []


def test_view_program_modalities_always_empty():
    """Intakes dropped `modalities` too (it left the `Program`); the
    view-model key stays `[]`."""
    v = post_card_view(_make_program_post())
    assert v["modalities"] == []


# --- post_card_view: defensiveness --------------------------------------


def test_view_unknown_kind_returns_base_skeleton():
    """An unregistered kind returns the all-None skeleton — templates
    render nothing rather than crashing on a missing detail relationship."""
    v = post_card_view(SimpleNamespace(kind="mystery"))
    assert v["kind"] == "mystery"
    assert v["kind_verb"] is None
    assert v["headline"] is None
    assert v["services"] == []


def test_view_cr_missing_detail_returns_base_skeleton():
    """A CR post with no detail relationship (shouldn't happen at
    rest, but the helper stays defensive for stub data) returns the
    skeleton with kind/kind_verb still populated."""
    v = post_card_view(SimpleNamespace(kind="referral", referral_detail=None))
    assert v["kind"] == "referral"
    assert v["kind_verb"] == "Seeking"
    assert v["headline"] is None
    assert v["location_chunk"] is None


def test_view_pa_missing_clinician_returns_partial_view():
    """PA's detail has a `clinician` relationship that could be None
    in test stubs, and the affiliation stub may be sparse. View-model
    populates the announcement core + self-describing profile and
    whatever affiliation context exists, leaving the rest at None
    instead of crashing."""
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            clinician=None,
            clinician_affiliation=SimpleNamespace(org=None),
            # Self-describing profile is on the detail row now.
            services=["psychotherapy"],
            description="x",
            schedule_text=None,
        ),
    )
    v = post_card_view(post)
    assert v["headline"] is None
    assert v["header_state"] is None
    assert v["full_address"] is None
    assert v["practice_link"] is None
    assert v["organization_link"] is None
    # The opening's own profile still populates so the card can render
    # whatever it can.
    assert v["services"] == ["psychotherapy"]
    assert v["description"] == "x"


def test_view_returns_dict_for_jinja_attribute_access():
    """Templates use ``view.field_name`` syntax — Jinja resolves this
    to ``view['field_name']`` on a dict. Pin that the function returns
    a dict (not a NamedTuple or dataclass) so the access pattern
    works without surprises."""
    v = post_card_view(_make_cr_post())
    assert isinstance(v, dict)
    assert v["kind"] == "referral"


# --- post_card_view: poster_name ----------------------------------------


def test_poster_name_opening_uses_clinician_first_last():
    v = post_card_view(_make_pa_post())
    assert v["poster_name"] == "Jane Smith"


def test_poster_name_opening_partial_name():
    v = post_card_view(
        _make_pa_post(clinician_attrs={"first_name": "Jane", "last_name": None})
    )
    assert v["poster_name"] == "Jane"


def test_poster_name_opening_none_when_no_names():
    v = post_card_view(
        _make_pa_post(clinician_attrs={"first_name": None, "last_name": None})
    )
    assert v["poster_name"] is None


def test_poster_name_opening_none_when_no_clinician():
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            clinician=None,
            services=[],
            settings=[],
            age_groups=[],
            languages=[],
            genders=[],
            description=None,
            schedule_text=None,
            website=None,
            referral_instructions=None,
        ),
    )
    assert post_card_view(post)["poster_name"] is None


def test_poster_name_intake_uses_org_name():
    v = post_card_view(_make_program_post())
    assert v["poster_name"] == "Acme Health"


def test_poster_name_intake_none_when_no_org():
    v = post_card_view(_make_program_post(program_attrs={"organization": None}))
    assert v["poster_name"] is None


def test_poster_name_referral_uses_referring_clinician_name():
    """`poster_name` is the referring clinician's name (#1454 FK), not
    the post owner's first clinician — the owner is a user; the
    referrer is the named clinician they're acting on behalf of."""
    v = post_card_view(_make_cr_post())
    assert v["poster_name"] == "Carlos Rivera"


def test_poster_name_referral_legacy_falls_back_to_owner_clinician():
    """Pre-#1454 rows: no `referring_clinician`, falls back to the post
    owner's first clinician."""
    post = _make_cr_post(referring_clinician_attrs=None)
    post.owner = SimpleNamespace(
        clinicians=[SimpleNamespace(first_name="Maya", last_name="Patel")]
    )
    assert post_card_view(post)["poster_name"] == "Maya Patel"


def test_poster_name_referral_legacy_none_when_no_owner_clinicians():
    post = _make_cr_post(referring_clinician_attrs=None)
    post.owner = SimpleNamespace(clinicians=[])
    assert post_card_view(post)["poster_name"] is None


def test_poster_name_referral_none_when_referring_clinician_has_no_name():
    """Defensive — a referring clinician with no name returns
    `poster_name=None` (the macro's name-or-id guard then suppresses the
    card)."""
    post = _make_cr_post(
        referring_clinician_attrs={"first_name": None, "last_name": None}
    )
    assert post_card_view(post)["poster_name"] is None


# --- post_row_summary ---------------------------------------------------


def test_row_summary_referral_description_carrier_city():
    """Primary path: description + first carrier label + city joined
    with ' · ' (#1358 PR-e — `insurance_carriers` is a list; the
    row summary picks the first to fit the single-line layout)."""
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            description="Complex PTSD, seeking weekly EMDR",
            insurance_carriers=["aetna"],
            location_city="Berkeley",
            age_groups=["adults_25_64"],
        ),
    )
    assert (
        post_row_summary(post) == "Complex PTSD, seeking weekly EMDR · Aetna · Berkeley"
    )


def test_row_summary_referral_no_carrier_no_city():
    """When carriers list is empty and city is absent only the
    description is returned."""
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            description="Needs a therapist",
            insurance_carriers=[],
            location_city=None,
            age_groups=["adults_25_64"],
        ),
    )
    assert post_row_summary(post) == "Needs a therapist"


def test_row_summary_referral_no_description_falls_back_to_headline():
    """When description is absent the age-based headline is used."""
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            description=None,
            insurance_carriers=[],
            location_city=None,
            age_groups=["adults_25_64"],
        ),
    )
    assert post_row_summary(post) == "Adult (25–64)"


def test_row_summary_referral_truncates_long_description():
    """Descriptions longer than 100 chars are truncated so rows stay readable."""
    long_desc = "x" * 150
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            description=long_desc,
            insurance_carriers=[],
            location_city=None,
            age_groups=["adults_25_64"],
        ),
    )
    summary = post_row_summary(post)
    assert len(summary) == 100
    assert summary == "x" * 100


def test_row_summary_referral_missing_detail():
    post = SimpleNamespace(kind="referral", referral_detail=None)
    assert post_row_summary(post) == "Referral"


def test_row_summary_opening_with_description_and_sliding_scale():
    """Opening with description + sliding scale (from the linked
    affiliation). Openings no longer carry `settings`, so the row summary
    is just the description plus the sliding-scale tag."""
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            description="2 slots open",
            age_groups=[],
            services=[],
            clinician_affiliation=SimpleNamespace(sliding_scale=True),
        ),
    )
    assert post_row_summary(post) == "2 slots open · sliding scale"


def test_row_summary_opening_no_description_builds_from_fields():
    """When opening has no description, age + service labels are used —
    both come from the opening detail row itself (services on the
    `ReferralService` vocab)."""
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            description=None,
            age_groups=["adults_25_64"],
            services=["therapy_individual"],
            clinician_affiliation=SimpleNamespace(sliding_scale=False),
        ),
    )
    summary = post_row_summary(post)
    assert "Adult (25–64)" in summary
    assert "Therapy — Individual" in summary


def test_row_summary_opening_no_sliding_scale():
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            description="Accepting new clients",
            clinician_affiliation=SimpleNamespace(
                settings=[], age_groups=[], services=[], sliding_scale=False
            ),
        ),
    )
    assert post_row_summary(post) == "Accepting new clients"


def test_row_summary_opening_missing_detail():
    post = SimpleNamespace(kind="clinician_opening", opening_detail=None)
    assert post_row_summary(post) == "Opening"


def test_row_summary_program_name_and_description():
    post = SimpleNamespace(
        kind="program_intake",
        intake_detail=SimpleNamespace(
            program=SimpleNamespace(name="RISE IOP"),
            description="Cohort starts June 1",
        ),
    )
    assert post_row_summary(post) == "RISE IOP · Cohort starts June 1"


def test_row_summary_unknown_kind_returns_empty_string():
    post = SimpleNamespace(kind="mystery")
    assert post_row_summary(post) == ""


# --- post_feed_headline -------------------------------------------------


def test_feed_headline_referral_is_demographics_only():
    """The title carries the client demographics only — the services that
    used to trail it now render as the `service_labels` fact row."""
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            age_groups=["adults_25_64"],
            services=["therapy_individual", "medication_management"],
        ),
    )
    assert post_feed_headline(post) == "Adult (25–64)"


def test_feed_headline_referral_no_services_returns_demographics_only():
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(
            age_groups=["adolescents_14_18"],
            services=[],
        ),
    )
    assert post_feed_headline(post) == "Adolescent (14–18)"


def test_feed_headline_referral_missing_detail_returns_fallback():
    post = SimpleNamespace(kind="referral", referral_detail=None)
    assert post_feed_headline(post) == "Referral"


def test_feed_headline_opening_is_practice_name_only():
    """The title is the practice's org name — services move to the focus."""
    post = _make_pa_post()
    assert post_feed_headline(post) == "Acme Counseling"


def test_feed_headline_opening_practice_name_when_no_focus():
    """Practice name is returned regardless of services/settings."""
    post = _make_pa_post(services=[], settings=[])
    assert post_feed_headline(post) == "Acme Counseling"


def test_feed_headline_opening_missing_detail_returns_fallback():
    post = SimpleNamespace(kind="clinician_opening", opening_detail=None)
    assert post_feed_headline(post) == "Opening"


def test_feed_headline_opening_missing_clinician_returns_fallback():
    post = SimpleNamespace(
        kind="clinician_opening",
        opening_detail=SimpleNamespace(
            clinician=None,
            clinician_affiliation=SimpleNamespace(
                services=["psychotherapy"], settings=[]
            ),
        ),
    )
    # Practice name cannot be derived; title falls back to "Opening".
    assert post_feed_headline(post) == "Opening"


def test_feed_headline_program_is_name_only():
    post = _make_program_post()
    assert post_feed_headline(post) == "RISE IOP"


def test_feed_headline_program_no_services_returns_name_only():
    post = _make_program_post(services=[])
    assert post_feed_headline(post) == "RISE IOP"


def test_feed_headline_unknown_kind_returns_empty_string():
    post = SimpleNamespace(kind="mystery")
    assert post_feed_headline(post) == ""


# --- derived headlines (no subject override) ----------------------------


def test_feed_headline_referral_derives_from_demographics():
    """Referrals derive their title from client demographics — there is no
    poster-set subject override on any kind."""
    post = SimpleNamespace(
        kind="referral",
        referral_detail=SimpleNamespace(age_groups=["adults_25_64"]),
    )
    assert post_feed_headline(post) == "Adult (25–64)"


def test_feed_headline_opening_is_practice_org_name():
    """An opening's title is always the linked practice's org name — the
    per-announcement `subject` override was dropped (#1507 follow-up)."""
    post = _make_pa_post()
    assert post_feed_headline(post) == "Acme Counseling"


# --- service_labels -----------------------------------------------------


def test_service_labels_priority_sorts_medication_management_first():
    """`medication_management` leads regardless of stored order; the rest
    follow in stored order. Every kind shares the one `ReferralService`
    vocab now."""
    view = {
        "kind": "referral",
        "services": ["therapy_group", "medication_management", "therapy_individual"],
    }
    assert service_labels(view) == [
        "Psychiatry / medication management",
        "Therapy — Group",
        "Therapy — Individual",
    ]


def test_service_labels_referral_uses_referral_vocab():
    view = {
        "kind": "referral",
        "services": ["therapy_individual", "medication_management"],
    }
    assert service_labels(view) == [
        "Psychiatry / medication management",
        "Therapy — Individual",
    ]


def test_service_labels_intake_uses_referral_vocab():
    """Intakes now share the single `ReferralService` vocab (no separate
    `settings` axis). `medication_management` still leads."""
    view = {
        "kind": "program_intake",
        "services": ["therapy_group", "medication_management"],
    }
    assert service_labels(view) == [
        "Psychiatry / medication management",
        "Therapy — Group",
    ]


def test_service_labels_empty_when_no_services():
    assert service_labels({"kind": "referral", "services": []}) == []


# --- location_summary ---------------------------------------------------


def test_location_summary_in_person_states_modality_city_and_state():
    """State leads (licensing); in-person names the city explicitly."""
    view = {
        "in_person": "yes",
        "virtual": "no",
        "location_chunk": {"city": "San Francisco", "state": "CA"},
    }
    assert location_summary(view) == "CA · In-person in San Francisco"


def test_location_summary_virtual_only_states_telehealth_no_in_person():
    """Telehealth-only: state leads, Telehealth is named, no in-person
    listed (and the city isn't shown — the work isn't place-bound)."""
    view = {
        "in_person": "no",
        "virtual": "yes",
        "location_chunk": {"city": "San Francisco", "state": "CA"},
    }
    assert location_summary(view) == "CA · Telehealth"


def test_location_summary_both_names_in_person_city_and_telehealth():
    view = {
        "in_person": "yes",
        "virtual": "yes",
        "location_chunk": {"city": "San Francisco", "state": "CA"},
    }
    assert location_summary(view) == "CA · In-person in San Francisco · Telehealth"


def test_location_summary_state_always_present_without_modality():
    view = {
        "in_person": None,
        "virtual": None,
        "location_chunk": {"city": "San Francisco", "state": "CA"},
    }
    assert location_summary(view) == "CA"


def test_location_summary_in_person_without_city_omits_where():
    view = {
        "in_person": "yes",
        "virtual": "no",
        "location_chunk": {"city": None, "state": "CA"},
    }
    assert location_summary(view) == "CA · In-person"


def test_location_summary_none_when_no_city_or_state():
    assert location_summary({"in_person": "yes", "virtual": "no"}) is None


# --- post_card_view: detail-row auto-forward ---------------------
# The passthrough fields are copied off the detail row by a single
# table-driven helper, not hand-listed per kind. These pin that
# contract so a new passthrough field can't be silently dropped from
# one kind's block: add it to `_SCALAR_PASSTHROUGH` / `_LIST_PASSTHROUGH`
# and it forwards for every kind that has the attribute.


@pytest.mark.parametrize(
    "make_post",
    [_make_cr_post, _make_pa_post, _make_program_post],
    ids=["referral", "opening", "intake"],
)
def test_passthrough_keys_present_for_every_kind(make_post):
    """Every declared passthrough field surfaces in the view for every
    kind — scalars as a value-or-None key, lists as a (possibly empty)
    list. `genders` is excluded: referral overrides it from its single
    `gender` column, so its forwarded value is recomputed downstream."""
    v = post_card_view(make_post())
    for view_key in _SCALAR_PASSTHROUGH:
        assert view_key in v
    for view_key in _LIST_PASSTHROUGH:
        assert isinstance(v[view_key], list)


def test_passthrough_forwards_detail_values_for_opening():
    """An opening's detail-row scalars/lists land on the view verbatim,
    proving the passthrough helper reads the right attributes (no rename
    drift). The opening's self-describing profile (services / age_groups /
    genders / cost) is on the detail row too and forwards the same way —
    see the dedicated profile read tests below."""
    v = post_card_view(
        _make_pa_post(
            description="Forwarded description",
            schedule_text="Forwarded schedule",
            services=["medication_management"],
            cost="$200",
        )
    )
    assert v["description"] == "Forwarded description"
    assert v["schedule_text"] == "Forwarded schedule"
    assert v["services"] == ["medication_management"]
    assert v["cost"] == "$200"


def test_passthrough_missing_attr_falls_back_to_base_default():
    """A referral detail row has no `settings` / `schedule_text`
    columns. The helper uses `getattr(..., None)`, so those keep the
    base defaults (`[]` for lists, `None` for scalars) rather than
    raising — that's why referral can share the same forwarding pass."""
    v = post_card_view(_make_cr_post())
    assert v["settings"] == []
    assert v["schedule_text"] is None


# --- opening profile reads: self-describing detail + steady-state context
#
# The opening is self-describing now: ``services`` / ``age_groups`` /
# ``genders`` / ``session_format`` / ``cost`` read off the
# ``OpeningDetail`` row itself. Only steady-state context (location,
# insurance, how-to-refer) reads from the linked ``ClinicianAffiliation``,
# and ``languages`` from the linked ``Clinician``. ``settings`` /
# ``modalities`` were dropped for openings (always ``[]``). The intake
# side still reads its whole steady-state profile from ``Program``.


def test_opening_reads_services_from_detail():
    """``view.services`` comes from the opening's own detail row, not the
    linked affiliation."""
    post = _make_pa_post()
    post.opening_detail.services = ["medication_management", "group_therapy"]
    v = post_card_view(post)
    assert v["services"] == ["medication_management", "group_therapy"]


def test_opening_reads_age_groups_and_genders_from_detail():
    """The cohort the opening serves (``age_groups`` / ``genders``) is
    self-describing — read off the detail row."""
    post = _make_pa_post()
    post.opening_detail.age_groups = ["children_6_10", "adolescents_14_18"]
    post.opening_detail.genders = ["male"]
    v = post_card_view(post)
    assert v["ages"] == ["children_6_10", "adolescents_14_18"]
    assert v["genders"] == ["male"]


def test_opening_settings_and_modalities_always_empty():
    """Openings dropped both axes; the view-model keys stay ``[]``
    regardless of what the affiliation carries."""
    v = post_card_view(_make_pa_post())
    assert v["settings"] == []
    assert v["modalities"] == []


def test_opening_no_affiliation_still_reads_self_describing_profile():
    """No ``clinician_affiliation`` relationship loaded at all → the
    steady-state context reads empty, but the opening's own profile
    (services / genders, on the detail row) still populates."""
    post = _make_pa_post()
    post.opening_detail.clinician_affiliation = None
    v = post_card_view(post)
    # Self-describing profile still reads (it's on the detail row).
    assert v["services"] == ["psychotherapy"]
    assert v["genders"] == ["female", "non_binary"]
    # Steady-state context reads empty without an affiliation.
    assert v["location_chunk"] is None
    assert v["in_network_carriers"] == []


def test_opening_reads_languages_from_clinician_not_affiliation():
    """``languages`` is person-level on the opening side (#1358):
    it lives on ``Clinician``, not ``ClinicianAffiliation``. Pin
    that the view reads it through the clinician relationship."""
    post = _make_pa_post()
    post.opening_detail.clinician.languages = ["en", "zh"]
    v = post_card_view(post)
    assert v["languages"] == ["en", "zh"]


def test_opening_practice_facts_come_from_its_affiliation_not_clinician_proxy():
    """Regression: a multi-affiliation clinician's `Clinician` model
    exposes primary-affiliation proxy properties (`location_city`,
    `in_network_carriers`, `org`, …). An opening posted under a
    NON-primary affiliation must show that affiliation's facts, so the
    view must read them from `opening_detail.clinician_affiliation` —
    never through the clinician proxies. The clinician stub here
    carries the conflicting primary-practice values; none of them may
    leak into the view (or the posture helper)."""
    post = _make_pa_post()
    # The clinician's primary affiliation (proxied on the model) is a
    # DIFFERENT practice than the one this opening announces.
    post.opening_detail.clinician = SimpleNamespace(
        id="prov-1",
        first_name="Jane",
        last_name="Smith",
        languages=["en"],
        org=SimpleNamespace(id="org-OTHER", name="Primary Practice"),
        location_city="Oakland",
        location_state="CA",
        location_zip="94601",
        in_person_sessions="no",
        virtual_sessions="no",
        in_network_carriers=["cigna"],
        accepts_out_of_network=True,
        sliding_scale=False,
        cost="$999/session",
    )
    v = post_card_view(post)
    assert v["headline"] == "Acme Counseling"
    assert v["practice_link"] == {"id": "prov-1", "name": "Acme Counseling"}
    assert v["organization_link"] == {"id": "org-1", "name": "Acme Counseling"}
    # Location comes from the announced affiliation (city/state, no ZIP) —
    # not the clinician proxy's Oakland/CA.
    assert v["location_chunk"] == {"city": "Brooklyn", "state": "NY", "zip": None}
    assert v["full_address"] == "Brooklyn, NY"
    # in_person/virtual derive from the opening's own session_format
    # (both), not the proxy's "no"/"no" session columns.
    assert v["in_person"] == "yes"
    assert v["virtual"] == "yes"
    # Insurance posture reads the announced affiliation's in-network
    # carriers, not the proxy's cigna.
    assert insurance_posture_for_post(post) == "in_network"


# --- provider_ref: the "who's behind this post" denotation --------------
#
# `provider_ref` is the single source for the hyperlinked "<name> · <org>"
# the detail card and the feed byline both render. These pin the per-kind
# shape so the macro can rely on it.


def test_provider_ref_opening_is_clinician_then_org():
    v = post_card_view(_make_pa_post())
    assert v["provider_ref"] == {
        "name": "Jane Smith",
        "entity": "clinician",
        "id": "prov-1",
        "org": {"id": "org-1", "name": "Acme Counseling"},
    }


def test_provider_ref_opening_solo_clinician_has_no_org():
    """A sole-proprietor clinician (affiliation with no org) yields
    ``org=None`` — the macro then renders just the linked name."""
    v = post_card_view(_make_pa_post(org=None))
    assert v["provider_ref"]["entity"] == "clinician"
    assert v["provider_ref"]["name"] == "Jane Smith"
    assert v["provider_ref"]["id"] == "prov-1"
    assert v["provider_ref"]["org"] is None


def test_provider_ref_intake_is_program_then_org():
    v = post_card_view(_make_program_post())
    assert v["provider_ref"] == {
        "name": "RISE IOP",
        "entity": "program",
        "id": "prog-1",
        "org": {"id": "org-h", "name": "Acme Health"},
    }


def test_provider_ref_referral_is_referring_clinician_then_affiliation_org():
    """A referral resolves to the referring clinician (#1454 FK) with
    the affiliation's org as the second part — the same `provider_ref`
    shape openings use, which the detail page renders in the "Connect with
    the provider" card (hyperlinked identity + org)."""
    v = post_card_view(_make_cr_post())
    assert v["provider_ref"] == {
        "name": "Carlos Rivera",
        "entity": "clinician",
        "id": "ref-clin-1",
        "org": {"id": "org-ref", "name": "River Health"},
    }


def test_provider_ref_referral_sole_prop_has_no_org():
    """A referring clinician with no affiliation (sole-prop or
    affiliation FK left null) yields ``org=None`` — the macro renders
    just the linked clinician name."""
    v = post_card_view(_make_cr_post(referring_affiliation_attrs=None))
    assert v["provider_ref"]["entity"] == "clinician"
    assert v["provider_ref"]["name"] == "Carlos Rivera"
    assert v["provider_ref"]["id"] == "ref-clin-1"
    assert v["provider_ref"]["org"] is None


def test_provider_ref_referral_legacy_falls_back_to_owner_clinician():
    """Pre-#1454 rows lack ``referring_clinician_id``. The view falls
    back to the post owner's first clinician as a name-only reference
    so legacy posts still surface a poster name; the owner-context
    card's identity row then renders unhyperlinked plain text."""
    v = post_card_view(_make_cr_post(referring_clinician_attrs=None))
    assert v["provider_ref"] == {
        "name": "Carlos Rivera",
        "entity": None,
        "id": None,
        "org": None,
    }


def test_owner_address_referral_from_referring_affiliation():
    """The owner-context card's Address row reads ``view.owner_address`` —
    the referring clinician's affiliation address, distinct from
    ``view.full_address`` (the client location)."""
    v = post_card_view(_make_cr_post())
    assert v["owner_address"] == "Cambridge, MA 02139"
    assert v["full_address"] == "Brooklyn, NY"


def test_owner_address_referral_none_when_no_affiliation():
    """Sole-prop / legacy case — no affiliation means no provider
    address. The macro suppresses the row when ``owner_address`` is
    ``None``."""
    v = post_card_view(_make_cr_post(referring_affiliation_attrs=None))
    assert v["owner_address"] is None


def test_owner_address_opening_matches_full_address():
    """For an opening, the provider's address IS the affiliation
    address — both keys hold the same string, so the owner-context card
    and the post-own facts block read consistent values."""
    v = post_card_view(_make_pa_post())
    assert v["owner_address"] == v["full_address"]
    assert v["owner_address"] == "Brooklyn, NY"


def test_intake_reads_services_and_genders_from_detail():
    """After the program-intake remodel the intake's announcement profile
    (``services`` / ``age_groups`` / ``genders`` / ``cost``) is
    self-describing — read off the ``IntakeDetail`` row, not the linked
    ``Program``."""
    post = _make_program_post()
    post.intake_detail.services = ["medication_management"]
    post.intake_detail.age_groups = ["children_6_10", "adolescents_14_18"]
    post.intake_detail.genders = ["female"]
    post.intake_detail.cost = "$80/session"
    v = post_card_view(post)
    assert v["services"] == ["medication_management"]
    assert v["ages"] == ["children_6_10", "adolescents_14_18"]
    assert v["genders"] == ["female"]
    assert v["cost"] == "$80/session"


def test_intake_reads_languages_from_program():
    """``languages`` is the one field that stays Program-level on the
    intake side — distinct from the opening side, where it's on the
    Clinician. The intake's profile (services / age_groups / genders /
    cost) reads off the detail row instead."""
    post = _make_program_post()
    post.intake_detail.program.languages = ["en", "es"]
    v = post_card_view(post)
    assert v["languages"] == ["en", "es"]


def test_intake_no_program_still_reads_self_describing_profile():
    """Defensive — an intake without a Program relationship (unrealistic
    but possible for stub fixtures) reads ``languages`` empty (it lived on
    the Program), but its own self-describing profile (services, on the
    detail row) still populates."""
    post = _make_program_post()
    post.intake_detail.services = ["medication_management"]
    post.intake_detail.program = None
    v = post_card_view(post)
    # Self-describing profile still reads (it's on the detail row).
    assert v["services"] == ["medication_management"]
    # `languages` was Program-level → empty without a Program.
    assert v["languages"] == []


def test_feed_headline_opening_reads_practice_name_from_affiliation():
    """``post_feed_headline`` for openings reads the practice name from the
    linked affiliation's org; the services fact reads the opening's own
    ``services`` (on the detail row) via the view-model + `service_labels`."""
    post = _make_pa_post()
    # Practice name still comes from the affiliation's org.
    post.opening_detail.clinician_affiliation = SimpleNamespace(
        org=SimpleNamespace(id="org-1", name="Acme Counseling"),
        location_city=None,
        location_state=None,
        in_network_carriers=[],
        accepts_out_of_network=None,
        sliding_scale=None,
    )
    # Services are self-describing — on the opening detail row, on the
    # `ReferralService` vocab (so `medication_management` → its referral label).
    post.opening_detail.services = ["medication_management"]
    assert post_feed_headline(post) == "Acme Counseling"
    assert service_labels(post_card_view(post)) == [
        "Psychiatry / medication management"
    ]


def test_row_summary_opening_reads_age_and_services_from_detail():
    """``post_row_summary`` for openings reads ``age_groups``/``services``
    from the opening detail row (services on the `ReferralService` vocab)."""
    post = _make_pa_post(description=None)
    post.opening_detail.age_groups = ["adults_25_64"]
    post.opening_detail.services = ["therapy_group"]
    summary = post_row_summary(post)
    assert "Therapy — Group" in summary


# --- Picker options ------------------------------------------------------


def _aff(id_, first="Jane", last="Smith", org=None):
    return SimpleNamespace(
        id=id_,
        clinician=SimpleNamespace(first_name=first, last_name=last),
        org=SimpleNamespace(name=org) if org else None,
    )


def _user_with(affs=(), programs=()):
    return SimpleNamespace(
        clinicians=[SimpleNamespace(clinician_affiliations=list(affs))],
        programs=list(programs),
    )


def test_affiliation_options_labels_person_first_org_second():
    user = _user_with([_aff("a1", org="Acme"), _aff("a2", first="Solo", last="Doc")])
    assert affiliation_options(user) == [
        ("a1", "Jane Smith · Acme"),
        ("a2", "Solo Doc"),
    ]


def test_affiliation_options_appends_current_when_owner_lacks_it():
    user = _user_with([_aff("a1")])
    current = _aff("a9", first="Other", last="Person", org="Group")
    assert affiliation_options(user, current) == [
        ("a1", "Jane Smith"),
        ("a9", "Other Person · Group"),
    ]


def test_affiliation_options_does_not_duplicate_current():
    a1 = _aff("a1")
    assert affiliation_options(_user_with([a1]), a1) == [("a1", "Jane Smith")]


def _program(id_, name, org):
    return SimpleNamespace(id=id_, name=name, organization=SimpleNamespace(name=org))


def test_program_options_appends_current_once():
    p1 = _program("p1", "IOP", "Acme")
    p9 = _program("p9", "PHP", "Other")
    user = _user_with(programs=[p1])
    assert program_options(user, p9) == [("p1", "IOP · Acme"), ("p9", "PHP · Other")]
    assert program_options(user, p1) == [("p1", "IOP · Acme")]
