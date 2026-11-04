"""View helpers for posts — pure functions consumed by templates.

The listing row in `src/domain/templates/posts/_item.html` needs a single
3-state "insurance posture" axis to render as one icon badge. The two
kinds model the underlying data with parallel shapes:

  * `referral` — an `insurance_carriers` JSON list of
    `INSURANCE_CARRIERS` tokens (non-empty = in-network; no boolean) plus
    an independent `accepts_private_pay` boolean. The posture is derived
    in priority order: in-network (carriers present) → private-pay →
    `None` (no signal set).
  * `opening` → linked `ClinicianAffiliation` — the
    `in_network_carriers` list (empty = no in-network) plus the
    `accepts_out_of_network` / `sliding_scale` booleans.

`insurance_posture_for_post(post)` collapses both shapes to a value
from `INSURANCE_POSTURES` (see `src/domain/models/enums.py`), or `None`
when no payment signal is set. The
ordering of branches is the priority the row should show: if a
clinician accepts in-network plans, that's the posture, even if they
also offer sliding scale — the in-network signal is louder.

`referral_headline(detail)` composes the CR card's headline text from
`age_groups[0]` and `pronouns` — e.g. "Adult she/her (25–64)", or
"Adult (25–64)" when pronouns is empty. CR posts
describe one client, so the first age group is the client's age (the
schema still allows multi for forward-compat but only the first drives
the title).

`post_card_view(post)` is the unified view-model that both the listing
card (`_item.html`) and the detail page (`detail.html`) read from. All
three kinds are **self-describing**: each detail row holds its own
``services`` / ``age_groups`` / ``genders`` / ``cost`` (referral + opening
also ``session_format``; referral its location). Each reads only
steady-state *context* from its linked entity: the opening reads location
+ insurance from the linked ``ClinicianAffiliation`` (the practice it
announces, NOT the clinician's primary-affiliation proxies — a
multi-affiliation clinician's opening must show the posting practice's
facts) and ``languages`` from the linked ``Clinician``; the intake reads
``languages`` from the linked ``Program``. The function collapses those
shapes into one flat dict so templates iterate over keys rather than
branching on `post.kind`. Values that don't apply to a kind are ``None``
(or empty lists — e.g. no kind carries ``settings`` / ``modalities``
anymore); templates render via ``{% if view.x %}``. Raw enum values are
returned — display-label lookup is the template's job.

`post_feed_headline(post)` builds the feed-row headline for the home and
browse list views: client demographics for referrals, the practice's org
name for openings, the program name for intakes (the clinical detail
trails as a separate `service_labels` fact row, not in the title).

`affiliation_options(user, current)` / `program_options(user, current)`
build the practice / program picker options for the post create + edit
forms. The caller passes the *post's owner* on edit (``current_user`` on
create, where the submitter becomes the owner) — never the viewer, so a
superuser editing someone else's post sees that owner's practices, not
their own. ``current`` (the post's linked affiliation / program) is
appended when the owner's list doesn't already contain it: an org rep
may post under an affiliated clinician they don't own, and the picker
must not silently re-point such a post on save.

All helpers are exposed as Jinja globals by
`src/framework/rendering/templating.py`.
"""

from typing import Any
from uuid import UUID

from src.domain.models.enums import (
    CLIENT_AGE_GROUP_LABELS_SINGULAR,
    CLIENT_AGE_GROUPS_BY_KEY,
    INSURANCE_CARRIER_LABELS,
    PRONOUNS_LABELS,
    REFERRAL_SERVICE_LABELS,
)
from src.framework.rendering.address import full_address


# Back-derivation: referral's `session_format` is a list[str] subset
# of {"in_person", "virtual"}; the cross-kind list/detail templates
# still read `view.in_person` / `view.virtual` as "yes"/"no"/None, so
# we lift list membership onto those keys. An empty list (no signal)
# leaves both as None.
def _in_person_from_session_format(session_format) -> str | None:
    if not session_format:
        return None
    return "yes" if "in_person" in session_format else "no"


def _virtual_from_session_format(session_format) -> str | None:
    if not session_format:
        return None
    return "yes" if "virtual" in session_format else "no"


def insurance_posture_for_post(post) -> str | None:
    """Map a `Post` (either kind) to one of `INSURANCE_POSTURES`.

    Returns `None` when the post has no detail row (shouldn't happen
    for persisted posts, but the row template tolerates it) or when no
    payment signal is set — the row/facts macros omit the chunk in
    both cases.
    """
    kind = getattr(post, "kind", None)
    if kind == "referral":
        detail = getattr(post, "referral_detail", None)
        if detail is None:
            return None
        # Map the referral's payment signals to the unified posture vocab
        # in priority order: in-network > private-pay > None. In-network is
        # read off carrier presence (a non-empty `insurance_carriers` list
        # is the in-network statement — no separate boolean), matching the
        # provider-side collapse below.
        if getattr(detail, "insurance_carriers", None):
            return "in_network"
        if getattr(detail, "accepts_private_pay", False):
            return "self_pay"
        return None
    if kind == "clinician_opening":
        detail = getattr(post, "opening_detail", None)
        affiliation = (
            getattr(detail, "clinician_affiliation", None)
            if detail is not None
            else None
        )
        if affiliation is None:
            return None
        if getattr(affiliation, "in_network_carriers", None):
            return "in_network"
        if getattr(affiliation, "accepts_out_of_network", None):
            return "out_of_network"
        # `cost` is per-announcement now (on the opening detail); sliding
        # scale stays on the affiliation.
        if getattr(affiliation, "sliding_scale", None) or getattr(detail, "cost", None):
            return "self_pay"
        return None
    if kind == "program_intake":
        # Program-availability has no insurance posture today — insurance
        # is modeled on the Clinician (who delivers care) and on the
        # Client-referral Post (the referral situation), not on the
        # Program (#537 docstring on `Program`). Return None so the
        # listing row omits the chunk entirely; the detail page does
        # the same.
        return None
    return None


_KIND_VERB = {
    "referral": "Seeking",
    "clinician_opening": "Providing",
    "program_intake": "Providing",
}


def _location_chunk(
    city: str | None, state: str | None, zip_code: str | None
) -> dict | None:
    """Return ``{city, state, zip}`` when any of the three are present,
    otherwise ``None`` so templates can ``{% if view.location_chunk %}``."""
    if not any((city, state, zip_code)):
        return None
    return {"city": city, "state": state, "zip": zip_code}


# Fields copied straight off the kind's detail row with no transform, as
# `view_key -> detail_attribute`. `_forward_detail_passthrough` applies these
# for every kind before its per-kind block fills in computed/relational fields.
# A kind whose detail lacks an attribute (referral has no `settings` /
# `schedule_text` / `genders`) just keeps the base default. Adding a plain
# field to a post kind means one line here, not an edit to three per-kind
# blocks — so a passthrough field can't be silently dropped from the view-model.
_SCALAR_PASSTHROUGH: dict[str, str] = {
    "description": "description",
    "schedule_text": "schedule_text",
    # `cost` is per-announcement on the opening + intake detail rows.
    # Referral has no `cost` attr (→ None).
    "cost": "cost",
}
_LIST_PASSTHROUGH: dict[str, str] = {
    "services": "services",
    "settings": "settings",
    "ages": "age_groups",
    "genders": "genders",
    "languages": "languages",
}

# Both provider post kinds now carry their own announcement profile
# (``services`` / ``age_groups`` / ``genders`` / ``cost``) on the detail
# row — read via the passthrough above. Only ``languages`` is steady-state:
# person-level on the linked ``Clinician`` for an opening, program-level on
# the linked ``Program`` for an intake. Each kind's block sets it directly.


def _forward_detail_passthrough(base: dict[str, Any], d: Any) -> None:
    """Copy every passthrough field off detail row ``d`` into ``base``.

    Scalars land as-is (``None`` when absent); list fields are normalized to
    a fresh list (``[]`` when absent or empty) so templates can iterate
    without nullability handling. Mutates ``base`` in place."""
    for view_key, attr in _SCALAR_PASSTHROUGH.items():
        base[view_key] = getattr(d, attr, None)
    for view_key, attr in _LIST_PASSTHROUGH.items():
        base[view_key] = list(getattr(d, attr, None) or [])


def _read_list(home: Any, attr: str) -> list:
    """Steady-state list field read from the new home (affiliation /
    clinician / program). Returns a fresh list so templates can iterate
    without nullability handling. ``None`` / missing home → ``[]``."""
    return list((getattr(home, attr, None) if home is not None else None) or [])


def _read_scalar(home: Any, attr: str):
    """Steady-state scalar field read from the new home. ``None`` /
    missing home → ``None``."""
    return getattr(home, attr, None) if home is not None else None


def post_card_view(post) -> dict[str, Any]:
    """Normalize a `Post` of any kind into the flat shape both the
    listing card and the detail page render from.

    Pre-pulls every field templates need so the per-kind branching
    happens here (once, in Python) instead of in three different
    templates. Missing values come back as ``None`` (scalars) or
    ``[]`` (lists) so templates render via ``{% if view.x %}`` /
    ``{% for x in view.xs %}`` without further nullability handling.

    Returns:
        kind: the discriminator (`referral` /
            `opening` / `intake`).
        kind_verb: ``"Seeking"`` for CR, ``"Providing"`` for the two
            availability kinds. Mirrors the kind-chip vocabulary the
            list card's left-edge color uses (orange = Seeking, cyan
            = Providing).
        headline: the card's identity line — CR is ``referral_headline``
            (age only after the gender column was removed); PA is the
            practice's org name; program is the program name.
        header_state: the state shown next to the headline. Program
            reads from ``program.state_preference``; CR and PA leave
            this ``None`` and surface their state via the
            demographics-column ``location_chunk`` row instead — that
            keeps the header line uncluttered and makes the two
            availability-vs-seeker kinds consistent on where location
            appears in the card.
        in_person / virtual: the post's in-person/virtual posture as
            `LOCATION_AVAILABILITY_OPTIONS` values. CR reads them off
            its own detail row; PA reads them from the linked
            ClinicianAffiliation's session-availability fields. Program
            has no in-person/virtual posture and returns ``None`` for
            both.
        services / settings: raw enum lists. PA + program carry
            ``settings``; CR's ``settings`` is empty.
        ages / languages / genders: raw enum lists. CR has no
            ``genders`` slot (the column was removed); opening/intake
            fill ``genders`` from the linked affiliation / program.
        insurance_posture: one of ``INSURANCE_POSTURES`` or ``None``
            (intake has no posture). Same value
            ``insurance_posture_for_post`` returns.
        location_chunk: ``{city, state, zip}`` for CR (from the
            detail row) and PA (from the linked ClinicianAffiliation) —
            the demographics-column icon-only row both render. ``None``
            for program (no location of its own; ``state_preference``
            still surfaces via ``header_state``).
        description: free-text description or ``None``. CR's
            description is NOT NULL on the model but the function
            stays defensive for stubs that omit it.
        schedule_text: PA/program optional schedule notes; ``None``
            for CR.
        provider_ref: the canonical "who's behind this post" reference —
            ``{name, entity, id, org}`` where ``entity`` is ``"clinician"``
            (opening, referral) or ``"program"`` (intake), ``id`` is that
            entity's id (``None`` when unlinkable — e.g. a legacy referral
            whose ``referring_clinician_id`` was never set), and ``org`` is
            ``{id, name}`` of the owning Organization or ``None`` (a
            sole-proprietor clinician has no org). The ``provider_ref``
            macro renders this as the hyperlinked "<name> · <org>"
            denotation on the detail card and the feed byline — one home
            for the format and the links across surfaces. For a referral
            the entity is the referring clinician (FK
            ``referral_detail.referring_clinician_id``) and the org comes
            from the affiliation the clinician is referring under
            (``referral_detail.clinician_affiliation``); pre-#1454 rows
            with no ``referring_clinician_id`` fall back to the post
            owner's first clinician as a name-only reference.
        practice_link: ``{id, name}`` — the linked Clinician's id with
            the affiliation's org name; ``None`` for other kinds.
        program_link: ``{id, name}`` of program's linked Program;
            ``None`` for other kinds.
        organization_link: ``{id, name}`` of the post's owning
            Organization (PA reads through ``clinician_affiliation.org``;
            program intake reads through ``program.organization``).
            ``None`` for referral (CR has no org linkage in the model).
            The owner-context card renders this as a clickable link so
            any post is one click from its org's detail page.
        full_address: ``"City, ST ZIP"`` string for the detail page's
            expanded location row — the post-own address. CR reads from
            its own client-location columns; PA reads from the linked
            ClinicianAffiliation; program returns ``None``.
        owner_address: ``"City, ST ZIP"`` string for the owner-context
            card's Address row — the provider-side address. PA's owner
            is the linked ClinicianAffiliation (same string as
            ``full_address``); referral's owner is the affiliation the
            referring clinician acts under
            (``referral_detail.clinician_affiliation``, distinct from the
            client location in ``full_address``); program returns
            ``None`` (programs have no address).
        accepts_private_pay: CR-only payment-path boolean from the detail
            row; ``None`` for other kinds. (Referrals have no in-network
            boolean — carrier presence is the in-network signal.)
        insurance_carriers: CR-only list of carrier tokens; empty list
            for CR with no carriers specified, ``[]`` for other kinds.
        in_network_carriers / accepts_out_of_network / sliding_scale:
            PA-only raw values from the linked ClinicianAffiliation,
            consumed by the feed-row meta strip (``_feed_row.html``).
            ``in_network_carriers`` comes back as an empty list when
            unset; the other two are ``None`` for other kinds.

    Opening ``cost`` is a view-model key (per-announcement, read off the
    opening detail). The "how to refer" pair (website, referral
    instructions) are NOT view-model keys — the detail page's owner-context
    card renders them straight off the linked ``ClinicianAffiliation`` /
    ``Program`` via the shared ``affiliation_facts`` / ``program_facts``
    macros.
    """
    kind = getattr(post, "kind", None)
    base: dict[str, Any] = {
        "kind": kind,
        "kind_verb": _KIND_VERB.get(kind),
        "headline": None,
        "header_state": None,
        "in_person": None,
        "virtual": None,
        # Referral + opening carry `session_format` (a list subset of
        # {in_person, virtual}); the two `in_person`/`virtual` keys are
        # back-derived from it. Intake sets it None.
        "session_format": None,
        "services": [],
        "settings": [],
        "ages": [],
        "languages": [],
        "genders": [],
        "insurance_posture": insurance_posture_for_post(post),
        "modalities": [],
        "cost": None,
        "location_chunk": None,
        "description": None,
        "schedule_text": None,
        "poster_name": None,
        "provider_ref": None,
        "practice_link": None,
        "program_link": None,
        "organization_link": None,
        "full_address": None,
        "owner_address": None,
        "sliding_scale": None,
        "accepts_private_pay": None,
        "insurance_carriers": [],
        "in_network_carriers": [],
        "accepts_out_of_network": None,
        "pronouns": [],
        "services_other_text": None,
        "insurance_carriers_other_text": None,
        "languages_other_text": None,
        "pronouns_other_text": None,
    }

    if kind == "referral":
        d = getattr(post, "referral_detail", None)
        if d is None:
            return base
        _forward_detail_passthrough(base, d)
        # Referring clinician comes from the FK the referral submitter
        # designates (#1454); the affiliation column gives us the org the
        # clinician is referring under (a multi-affiliation clinician
        # picks one per referral). Pre-#1454 rows lack the FK — fall back
        # to the post owner's first clinician as a name-only reference so
        # legacy posts still surface a poster name in the byline.
        _referring = getattr(d, "referring_clinician", None)
        _referring_aff = getattr(d, "clinician_affiliation", None)
        if _referring is not None:
            _fn = getattr(_referring, "first_name", None)
            _ln = getattr(_referring, "last_name", None)
            _poster = " ".join(filter(None, [_fn, _ln])) or None
            _org = getattr(_referring_aff, "org", None) if _referring_aff else None
            _org_name = getattr(_org, "name", None) if _org else None
            _org_ref = (
                {"id": _org.id, "name": _org_name}
                if _org and getattr(_org, "id", None) and _org_name
                else None
            )
            _provider_ref = {
                "name": _poster,
                "entity": "clinician",
                "id": getattr(_referring, "id", None),
                "org": _org_ref,
            }
            _owner_address = full_address(
                _read_scalar(_referring_aff, "location_city"),
                _read_scalar(_referring_aff, "location_state"),
                _read_scalar(_referring_aff, "location_zip"),
            )
        else:
            _owner = getattr(post, "owner", None)
            _owner_clinicians = getattr(_owner, "clinicians", None) or []
            _rc = _owner_clinicians[0] if _owner_clinicians else None
            _fn = getattr(_rc, "first_name", None) if _rc else None
            _ln = getattr(_rc, "last_name", None) if _rc else None
            _poster = " ".join(filter(None, [_fn, _ln])) or None
            _provider_ref = {
                "name": _poster,
                "entity": None,
                "id": None,
                "org": None,
            }
            _owner_address = None
        base.update(
            poster_name=_poster,
            provider_ref=_provider_ref,
            owner_address=_owner_address,
            headline=referral_headline(d),
            # Referral side stores `session_format` as a list[str]
            # subset of {in_person, virtual}; back-derive the two
            # `in_person`/`virtual` view keys so the cross-kind
            # list/detail templates (`posts/_item.html`,
            # `posts/detail.html`) render unchanged. Opening side
            # still reads from the affiliation's two independent
            # columns.
            session_format=list(getattr(d, "session_format", None) or []),
            in_person=_in_person_from_session_format(
                getattr(d, "session_format", None)
            ),
            virtual=_virtual_from_session_format(getattr(d, "session_format", None)),
            location_chunk=_location_chunk(
                getattr(d, "location_city", None),
                getattr(d, "location_state", None),
                None,
            ),
            full_address=full_address(
                getattr(d, "location_city", None),
                getattr(d, "location_state", None),
                None,
            ),
            accepts_private_pay=getattr(d, "accepts_private_pay", None),
            sliding_scale=getattr(d, "sliding_scale", None),
            insurance_carriers_other_text=getattr(
                d, "insurance_carriers_other_text", None
            ),
            insurance_carriers=list(getattr(d, "insurance_carriers", None) or []),
            pronouns=list(getattr(d, "pronouns", None) or []),
            services_other_text=getattr(d, "services_other_text", None),
            languages_other_text=getattr(d, "languages_other_text", None),
            pronouns_other_text=getattr(d, "pronouns_other_text", None),
        )
        return base

    if kind == "clinician_opening":
        d = getattr(post, "opening_detail", None)
        if d is None:
            return base
        _forward_detail_passthrough(base, d)
        p = getattr(d, "clinician", None)
        # The opening's announcement profile (services / age_groups /
        # genders / session_format / cost / services_other_text) is read
        # off the detail row itself — services / ages / genders land via
        # the passthrough above; the rest are set below. Only steady-state
        # context (org, location, insurance) reads from the affiliation the
        # opening announces — NOT through the Clinician's primary-affiliation
        # proxy, which would show the wrong practice for a multi-affiliation
        # clinician. `languages` stays person-level on the Clinician.
        affiliation = getattr(d, "clinician_affiliation", None)
        base["languages"] = _read_list(p, "languages")
        base["session_format"] = list(getattr(d, "session_format", None) or [])
        base["in_person"] = _in_person_from_session_format(base["session_format"])
        base["virtual"] = _virtual_from_session_format(base["session_format"])
        base["services_other_text"] = getattr(d, "services_other_text", None)
        _org = _read_scalar(affiliation, "org")
        _org_name = getattr(_org, "name", None) if _org else None
        _org_ref = (
            {"id": _org.id, "name": _org_name}
            if _org and getattr(_org, "id", None) and _org_name
            else None
        )
        _fn = getattr(p, "first_name", None) if p else None
        _ln = getattr(p, "last_name", None) if p else None
        _poster = " ".join(filter(None, [_fn, _ln])) or None
        base.update(
            poster_name=_poster,
            # Provider reference — the clinician, linked, followed by the
            # practice's org (sole-prop clinicians have `org=None`).
            provider_ref={
                "name": _poster,
                "entity": "clinician",
                "id": getattr(p, "id", None) if p else None,
                "org": _org_ref,
            },
            headline=_org_name,
            # `header_state` stays None — opening's location lives in
            # the demographics column via `location_chunk` (same row
            # treatment as referral). Both kinds match on where
            # location surfaces, so the list card's header line stays
            # uncluttered for both.
            header_state=None,
            # Affiliation location is city/area + state, no ZIP. `in_person`
            # / `virtual` are derived from the opening's own `session_format`
            # above (not from the affiliation).
            location_chunk=_location_chunk(
                _read_scalar(affiliation, "location_city"),
                _read_scalar(affiliation, "location_state"),
                None,
            ),
            practice_link=(
                {"id": p.id, "name": _org_name}
                if _org_name and p and getattr(p, "id", None)
                else None
            ),
            organization_link=_org_ref,
            full_address=full_address(
                _read_scalar(affiliation, "location_city"),
                _read_scalar(affiliation, "location_state"),
                None,
            ),
            # Owner-context card reads `owner_address` (the provider's
            # address). For an opening that's the same affiliation as
            # `full_address`; the duplication keeps `owner_address`'s
            # semantics ("provider-side address") consistent across kinds
            # so the macro can read one key.
            owner_address=full_address(
                _read_scalar(affiliation, "location_city"),
                _read_scalar(affiliation, "location_state"),
                None,
            ),
            # Feed-row meta strip (`_feed_row.html`) reads these three
            # for the opening insurance chunk.
            sliding_scale=_read_scalar(affiliation, "sliding_scale"),
            in_network_carriers=_read_list(affiliation, "in_network_carriers"),
            accepts_out_of_network=_read_scalar(affiliation, "accepts_out_of_network"),
        )
        return base

    if kind == "program_intake":
        d = getattr(post, "intake_detail", None)
        if d is None:
            return base
        _forward_detail_passthrough(base, d)
        prog = getattr(d, "program", None)
        _prog_org = getattr(prog, "organization", None) if prog else None
        # The intake's announcement profile (services / age_groups /
        # genders / cost) is read off the detail row via the passthrough
        # above. Only `languages` is steady-state — program-level on the
        # linked Program (unlike openings, where it's person-level on the
        # Clinician).
        base["languages"] = _read_list(prog, "languages")
        base["services_other_text"] = getattr(d, "services_other_text", None)
        _prog_name = getattr(prog, "name", None) if prog else None
        _org_ref = (
            {"id": _prog_org.id, "name": _prog_org.name}
            if _prog_org
            and getattr(_prog_org, "id", None)
            and getattr(_prog_org, "name", None)
            else None
        )
        base.update(
            poster_name=(getattr(_prog_org, "name", None) if _prog_org else None),
            # Provider reference — the program, linked, followed by its
            # owning org. Programs always FK to an org, so `org` is
            # normally set.
            provider_ref={
                "name": _prog_name,
                "entity": "program",
                "id": getattr(prog, "id", None) if prog else None,
                "org": _org_ref,
            },
            headline=_prog_name,
            header_state=(getattr(prog, "state_preference", None) if prog else None),
            program_link=(
                {"id": prog.id, "name": prog.name}
                if prog and getattr(prog, "id", None) and _prog_name
                else None
            ),
            organization_link=_org_ref,
        )
        return base

    return base


def referral_headline(detail) -> str:
    """Build the listing-card headline for a `referral`.

    Format: `"<Age noun> (<range>) · <pronouns>"` — age and range lead,
    then a mid-dot, then the pronouns: e.g. `"Adult (25–64) · she/her"`,
    `"Adolescent (14–18)"` when no pronouns are stated, or
    `"Adult (25–64) · she/her, they/them"` when multiple. Pronouns are
    capped at the first two to bound headline length. The mid-dot (not a
    comma) separates age from pronouns so multi-pronoun lists — which are
    themselves comma-joined — stay unambiguous. The age comes from
    `age_groups[0]` since a CR post describes one client; the schema still
    allows multi but the headline picks the first value.

    Returns `"Client Referral"` as a fallback when the detail has no
    age groups (defensive — schema requires min-1, so this shouldn't
    happen for persisted posts).
    """
    age_groups = getattr(detail, "age_groups", None) or []
    if not age_groups:
        return "Client Referral"
    age = CLIENT_AGE_GROUPS_BY_KEY[age_groups[0]]
    pronouns = list(getattr(detail, "pronouns", None) or [])
    if pronouns:
        pronoun_str = ", ".join(PRONOUNS_LABELS.get(p, p) for p in pronouns[:2])
        return f"{age.singular} ({age.range}) · {pronoun_str}"
    return f"{age.singular} ({age.range})"


def service_labels(view) -> list[str]:
    """Priority-sorted display labels for a post's services.

    `medication_management` leads; the remaining services follow in the
    post's stored order. Every post kind now shares the one
    `ReferralService` vocabulary (referral request side + the provider
    opening/intake sides), so there's a single label map. Returns ``[]``
    when the post states no services.

    Registered as a template global so all three service surfaces — the
    framework feed row, the domain list card (`services_fact`), and the
    referral detail page — render the identical ordering from one home,
    instead of the sort living in a domain macro the framework row can't
    import.
    """
    services = list(view.get("services") or [])
    priority = ("medication_management",)
    labels = [REFERRAL_SERVICE_LABELS.get(s, s) for s in priority if s in services]
    labels += [REFERRAL_SERVICE_LABELS.get(s, s) for s in services if s not in priority]
    return labels


def location_summary(view) -> str | None:
    """Location + session modality for a post, written to answer three
    questions at a glance — the identical string in the list card, feed
    row, and referral detail:

      * **State** — always shown first; licensing is state-scoped, so it's
        relevant even for telehealth-only work.
      * **In-person?** — and if so *where*: ``"In-person in <city>"`` (or
        a bare ``"In-person"`` when no city is on file).
      * **Telehealth?** — ``"Telehealth"`` when virtual sessions are offered.

    The offered modalities are mid-dot-joined after the state, so the
    reader sees exactly which apply: ``"CA · In-person in San Francisco ·
    Telehealth"``, ``"CA · Telehealth"`` (telehealth only — no in-person
    listed), ``"CA · In-person in San Francisco"`` (in-person only), or a
    bare ``"CA"`` when no modality is recorded. Reads the cross-kind
    ``in_person`` / ``virtual`` view keys (`LOCATION_AVAILABILITY`
    ``"yes"`` / ``"no"``) and ``location_chunk``. Returns ``None`` when
    there's neither a state nor a city to anchor on.

    Registered as a template global so all three surfaces honor the same
    rule from one home. (On the referral detail the row is redaction-aware
    — a non-verified viewer gets a locked field, so the in-person city
    never leaks.)
    """
    chunk = view.get("location_chunk") or {}
    state = chunk.get("state")
    city = chunk.get("city")
    if not state and not city:
        return None
    modes = []
    if view.get("in_person") == "yes":
        modes.append(f"In-person in {city}" if city else "In-person")
    if view.get("virtual") == "yes":
        modes.append("Telehealth")
    if modes:
        body = " · ".join(modes)
        return f"{state} · {body}" if state else body
    return state or city


def post_row_summary(post) -> str:
    """Build the compact mid-dot summary line for the row layout.

    Used by the home-page "My active posts" widget and the list-page row
    view. Returns a " · "-joined string of the post's key facts: the
    free-text description plus the one or two most differentiating
    metadata signals (first insurance carrier + city for referrals;
    settings + sliding-scale flag for openings).

    Truncates description to 100 chars so rows stay single-line on typical
    screens; metadata appended after the truncation so the separators
    always appear regardless of description length.
    """
    kind = getattr(post, "kind", None)

    if kind == "referral":
        d = getattr(post, "referral_detail", None)
        if d is None:
            return "Referral"
        parts: list[str] = []
        desc = getattr(d, "description", None)
        if desc:
            parts.append(desc[:100])
        else:
            parts.append(referral_headline(d))
        carriers = list(getattr(d, "insurance_carriers", None) or [])
        if carriers:
            parts.append(INSURANCE_CARRIER_LABELS.get(carriers[0], carriers[0]))
        city = getattr(d, "location_city", None)
        if city:
            parts.append(city)
        return " · ".join(parts)

    if kind == "clinician_opening":
        d = getattr(post, "opening_detail", None)
        if d is None:
            return "Opening"
        affiliation = getattr(d, "clinician_affiliation", None)
        parts = []
        desc = getattr(d, "description", None)
        if desc:
            parts.append(desc[:100])
        else:
            # `age_groups` / `services` are per-announcement (on the
            # opening detail); services use the `ReferralService` vocab.
            ages = list(getattr(d, "age_groups", None) or [])
            services = list(getattr(d, "services", None) or [])
            age_labels = [CLIENT_AGE_GROUP_LABELS_SINGULAR.get(a, a) for a in ages[:2]]
            svc_labels = [REFERRAL_SERVICE_LABELS.get(s, s) for s in services[:2]]
            combined = age_labels + svc_labels
            if combined:
                parts.append(", ".join(combined))
        if _read_scalar(affiliation, "sliding_scale"):
            parts.append("sliding scale")
        return " · ".join(parts) if parts else "Opening"

    if kind == "program_intake":
        d = getattr(post, "intake_detail", None)
        if d is None:
            return "Program"
        prog = getattr(d, "program", None)
        name = getattr(prog, "name", None) if prog else None
        desc = getattr(d, "description", None)
        parts = []
        if name:
            parts.append(name)
        if desc:
            parts.append(desc[:80])
        return " · ".join(parts) if parts else "Program"

    return ""


def post_feed_headline(post) -> str:
    """Build the feed-row title — the post's base identity line only.

    Referrals: always the client demographics (`referral_headline`), e.g.
    ``"Adult (25–64)"``. Openings: the practice's org name. Program
    intakes: the program name. No kind carries a poster-set ``subject``
    override — every headline is derived, matching the referral model.

    The clinical services that used to trail the title (the
    ``"… — Psychotherapy"`` suffix) now render as the `service_labels`
    fact row in the card, so the title stays a short, scannable identity
    line and the services aren't crammed into it.
    """
    kind = getattr(post, "kind", None)

    if kind == "referral":
        d = getattr(post, "referral_detail", None)
        if d is None:
            return "Referral"
        return referral_headline(d)

    if kind == "clinician_opening":
        d = getattr(post, "opening_detail", None)
        if d is None:
            return "Opening"
        affiliation = getattr(d, "clinician_affiliation", None)
        _org = _read_scalar(affiliation, "org")
        return (getattr(_org, "name", None) if _org else None) or "Opening"

    if kind == "program_intake":
        d = getattr(post, "intake_detail", None)
        if d is None:
            return "Program"
        prog = getattr(d, "program", None)
        return (getattr(prog, "name", None) if prog else None) or "Program"

    return ""


def _affiliation_label(aff) -> str:
    """Person first, org as disambiguator when present — "Jane Smith" or
    "Jane Smith · Acme Counseling"."""
    c = aff.clinician
    name = f"{c.first_name or ''} {c.last_name or ''}".strip()
    return f"{name} · {aff.org.name}" if aff.org else name


def affiliation_options(user, current=None) -> list[tuple[UUID, str]]:
    """`(affiliation_id, label)` options for the referral / opening
    practice picker — every affiliation of every clinician ``user`` owns,
    plus ``current`` when it isn't among them. See the module docstring
    for why ``user`` is the post's owner, not the viewer."""
    affs = [aff for c in user.clinicians for aff in c.clinician_affiliations]
    if current is not None and all(a.id != current.id for a in affs):
        affs.append(current)
    return [(aff.id, _affiliation_label(aff)) for aff in affs]


def program_options(user, current=None) -> list[tuple[UUID, str]]:
    """`(program_id, "<Program> · <Org>")` options for the program-intake
    picker — ``user``'s programs plus ``current`` when absent."""
    programs = list(user.programs)
    if current is not None and all(p.id != current.id for p in programs):
        programs.append(current)
    return [(p.id, f"{p.name} · {p.organization.name}") for p in programs]
