"""Domain-side Jinja globals.

The framework's templating env (`src/framework/rendering/templating.py`)
deliberately knows no entity-specific values. This module is where every
domain enum, per-kind create schema, and view helper is wired into the
env via `register_template_globals(...)` and `register_choice_labels(...)`.

Import-time side effects: the registration calls run when this module
loads, so callers ensure the trigger fires before any template renders.
Two trigger points cover the real load paths:

* `src/main.py` imports this module at app boot.
* `src/domain/__init__.py` re-imports it so any `from src.domain.X import Y`
  in a test or script populates the env before a render reaches for a
  global.
"""

from src.domain.logic import capabilities
from src.domain.logic.clinicians.view import clinician_card_view
from src.domain.logic.posts.schema import (
    ClinicianOpeningCreate,
    ProgramIntakeCreate,
    ReferralCreate,
)
from src.domain.logic.posts.sections import REFERRAL_SECTIONS
from src.domain.logic.posts.view import (
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
from src.domain.logic.saved_searches.urls import posts_url_for_filters
from src.domain.logic.users.view import onboarding_readiness
from src.domain.models import enums
from src.domain.models.posts.post_kinds import POST_KINDS
from src.framework.rendering.form_fields import register_choice_labels
from src.framework.rendering.templating import register_template_globals

# Expose the controlled-vocabulary tuples (and matching display-label
# dicts) from `src/domain/models/enums.py` as Jinja globals so per-kind
# form templates iterate over the same values that the schema's
# `Literal[*TUPLE]`s and the DB CHECK constraints render from. Adding a
# value to a tuple in `enums.py` then shows up everywhere — schema,
# DB, and form dropdown — without per-template edits. The label dicts
# are looked up in the form-render macro
# (`src/framework/templates/_shared/form_fields.html`); the
# `test_labels_cover_their_tuples` guardrail asserts every value in a
# tuple has a label.
register_template_globals(
    US_STATES=enums.US_STATES,
    LOCATION_AVAILABILITY_OPTIONS=enums.LOCATION_AVAILABILITY_OPTIONS,
    LOCATION_AVAILABILITY_LABELS=enums.LOCATION_AVAILABILITY_LABELS,
    SESSION_FORMATS=enums.SESSION_FORMATS,
    SESSION_FORMAT_LABELS=enums.SESSION_FORMAT_LABELS,
    CLIENT_AGE_GROUPS=enums.CLIENT_AGE_GROUPS,
    CLIENT_AGE_GROUP_LABELS=enums.CLIENT_AGE_GROUP_LABELS,
    CLIENT_AGE_GROUP_LABELS_SINGULAR=enums.CLIENT_AGE_GROUP_LABELS_SINGULAR,
    LANGUAGES=enums.LANGUAGES,
    LANGUAGE_LABELS=enums.LANGUAGE_LABELS,
    INSURANCE_CARRIERS=enums.INSURANCE_CARRIERS,
    INSURANCE_CARRIER_LABELS=enums.INSURANCE_CARRIER_LABELS,
    DESIRED_TIME_SLOTS=enums.DESIRED_TIME_SLOTS,
    DESIRED_TIME_SLOT_LABELS=enums.DESIRED_TIME_SLOT_LABELS,
    DESIRED_TIME_DAYS=enums.DESIRED_TIME_DAYS,
    DESIRED_TIME_DAY_LABELS=enums.DESIRED_TIME_DAY_LABELS,
    DESIRED_TIME_DAY_SHORT_LABELS=enums.DESIRED_TIME_DAY_SHORT_LABELS,
    DESIRED_TIME_PARTS=enums.DESIRED_TIME_PARTS,
    DESIRED_TIME_PART_LABELS=enums.DESIRED_TIME_PART_LABELS,
    REFERRAL_SERVICES=enums.REFERRAL_SERVICES,
    REFERRAL_SERVICE_LABELS=enums.REFERRAL_SERVICE_LABELS,
    GENDERS=enums.GENDERS,
    GENDER_LABELS=enums.GENDER_LABELS,
    PRONOUNS=enums.PRONOUNS,
    PRONOUNS_LABELS=enums.PRONOUNS_LABELS,
    INSURANCE_POSTURES=enums.INSURANCE_POSTURES,
    INSURANCE_POSTURE_LABELS=enums.INSURANCE_POSTURE_LABELS,
    # Affirming-identity vocabulary (#1358 PR-a). Referral request side
    # and Clinician person-level side both pull from this tuple; the
    # referral create/edit form's multi-checkbox renders directly from
    # the global.
    AFFIRMING_IDENTITIES=enums.AFFIRMING_IDENTITIES,
    AFFIRMING_IDENTITY_LABELS=enums.AFFIRMING_IDENTITY_LABELS,
    # LICENSE_TYPES and EDUCATION/CERTIFICATION equivalents are exposed here
    # as globals so bespoke templates (like the profile hub's license step)
    # can reference them without relying on CLINICIAN_ENTITY.static_context,
    # which only runs through the framework's generic entity handlers.
    LICENSE_TYPES=enums.LICENSE_TYPES,
    LICENSE_TYPES_LABELS=enums.LICENSE_TYPES_LABELS,
    EDUCATION_TYPES=enums.EDUCATION_TYPES,
    EDUCATION_TYPES_LABELS=enums.EDUCATION_TYPES_LABELS,
    CERTIFICATION_TYPES=enums.CERTIFICATION_TYPES,
    CERTIFICATION_TYPES_LABELS=enums.CERTIFICATION_TYPES_LABELS,
    # `LICENSE_TYPES`, `EDUCATION_TYPES`, `CERTIFICATION_TYPES` and
    # their `_LABELS` also flow into the context via
    # `CLINICIAN_ENTITY.static_context` (merged by `handle_detail` /
    # `handle_list` / `handle_get_edit_form`) so the spec remains the
    # single binding site for generic entity pages. `register_choice_labels`
    # below covers the form-field macro label lookup for both paths.
    #
    # Polymorphic posts have no single create-schema (the top-level
    # adapter is a discriminated union); the per-kind route handler
    # can't inject a `schema` context var without per-kind plumbing in
    # `PostKindSpec`, which would close an import cycle (post_kinds →
    # schema → models → post_kinds). Exposing the kind-specific
    # `*Create` schemas as Jinja globals lets the kind's form templates
    # pass the right schema to `field_for` without context-routing
    # changes. Per-kind form templates pick which to pass.
    opening_create_schema=ClinicianOpeningCreate,
    intake_create_schema=ProgramIntakeCreate,
    referral_create_schema=ReferralCreate,
    # `POST_KINDS` is the SOT for per-kind nouns + picker descriptions.
    # The /posts/form picker iterates this directly so the headings
    # (e.g. "Referral" / "Opening" / "Program intake") and their
    # taglines can't drift from the source. The sidebar filter's
    # `kind` choices and every "Create X" / "Edit X" headline also
    # read POST_KINDS[k].noun via the labels helpers. See
    # `src/domain/models/posts/post_kinds.py`.
    POST_KINDS=POST_KINDS,
    # `REFERRAL_SECTIONS` is the single source for the referral form's
    # section titles, shared by the write view (`_form_referral.html`
    # `form_section(...)`) and the read view (`_referral_facts.html`
    # `fact_group(...)`) so the mirrored headings can't drift. See
    # `src.domain.logic.posts.sections`.
    REFERRAL_SECTIONS=REFERRAL_SECTIONS,
    # Post-specific view helpers.
    insurance_posture=insurance_posture_for_post,
    referral_headline=referral_headline,
    # `post_card_view(post)` is the unified view-model both the listing
    # card (`posts/_item.html`) and the detail page (`posts/detail.html`)
    # read from — see its docstring in `src.domain.logic.posts.view`.
    post_card_view=post_card_view,
    # `post_row_summary(post)` — compact mid-dot summary line for the row
    # layout used by the home-page widget and list-page compact view.
    post_row_summary=post_row_summary,
    # `post_feed_headline(post)` — the feed row's base identity line
    # (demographics / practice / program name) for home and browse views.
    post_feed_headline=post_feed_headline,
    # `affiliation_options` / `program_options` — the post forms' picker
    # options, sourced from the post's owner (not the viewer). See
    # `src.domain.logic.posts.view`.
    affiliation_options=affiliation_options,
    program_options=program_options,
    # `service_labels(view)` / `location_summary(view)` — the priority-sorted
    # service labels and the one-line location (state + in-person-where +
    # telehealth), shared by the feed row, list card, and referral detail so
    # all three read one home.
    service_labels=service_labels,
    location_summary=location_summary,
    # `posts_url_for_filters(filters)` renders a saved search's stored
    # filter_values dict back into a `/posts?…` URL — the "open" half of
    # the saved-search round-trip. See `src.domain.logic.saved_searches.urls`.
    posts_url_for_filters=posts_url_for_filters,
    # `clinician_card_view(clinician)` is the unified view-model
    # `clinicians/detail.html` reads from — see its docstring in
    # `src.domain.logic.clinicians.view`.
    clinician_card_view=clinician_card_view,
    # `onboarding_readiness(user)` is the compact capability-accurate
    # readiness summary the "Getting started" checklist reads — see its
    # docstring in `src.domain.logic.users.view`. Reuses the same
    # `capabilities` predicates the post gate uses, so the checklist
    # can't invite a user into an action the server would 403.
    onboarding_readiness=onboarding_readiness,
    # `capabilities` is the single-source-of-truth predicate module
    # (`src.domain.logic.capabilities`) registered as a Jinja namespace
    # so templates can write
    # `{% if capabilities.can_post_referral(current_user) %}...`.
    # The same predicates are called from route `write_authz` paths, so
    # the visible-button and server-side block can't disagree.
    capabilities=capabilities,
)

# Register the choice-tuple → labels-dict mapping that `field_spec` uses
# to resolve labels for `Literal[*TUPLE]` fields. Lookup is by tuple
# identity, so the mapping needs to be populated before any template
# render. Tuples without a labels dict (USPS state codes are
# self-describing) register `None` so misses are explicit.
register_choice_labels(enums.US_STATES, None)
register_choice_labels(
    enums.LOCATION_AVAILABILITY_OPTIONS, enums.LOCATION_AVAILABILITY_LABELS
)
register_choice_labels(enums.SESSION_FORMATS, enums.SESSION_FORMAT_LABELS)
register_choice_labels(enums.CLIENT_AGE_GROUPS, enums.CLIENT_AGE_GROUP_LABELS)
register_choice_labels(enums.LANGUAGES, enums.LANGUAGE_LABELS)
register_choice_labels(enums.INSURANCE_CARRIERS, enums.INSURANCE_CARRIER_LABELS)
register_choice_labels(enums.REFERRAL_SERVICES, enums.REFERRAL_SERVICE_LABELS)
register_choice_labels(enums.GENDERS, enums.GENDER_LABELS)
register_choice_labels(enums.PRONOUNS, enums.PRONOUNS_LABELS)
register_choice_labels(enums.AFFIRMING_IDENTITIES, enums.AFFIRMING_IDENTITY_LABELS)
register_choice_labels(enums.LICENSE_TYPES, enums.LICENSE_TYPES_LABELS)
register_choice_labels(enums.EDUCATION_TYPES, enums.EDUCATION_TYPES_LABELS)
register_choice_labels(enums.CERTIFICATION_TYPES, enums.CERTIFICATION_TYPES_LABELS)
