"""Controlled-vocabulary `LabeledChoice` classes; derived tuple/dict aliases.

Every labeled vocabulary is a `LabeledChoice` subclass (see `labeled_choice.py`):
the class declares value + label + optional icon per member, and the historical
`FOO` / `FOO_LABELS` / `FOO_ICONS` names are kept as derived aliases
(`Cls.values()` / `.labels()` / `.icons()`) so every downstream consumer stays
unchanged. Vocabularies whose display facts are richer than value+label+icon
(`ClientAgeGroup`, `DesiredTimeDay`) subclass with a custom `__new__` that
attaches the extra attributes; their derived dicts read those off the members.

`US_STATES` is the one plain tuple left: the value (USPS abbreviation) is its
own user-facing label, so there's nothing to single-source — one structure, no
parallel dict to drift from.
"""

from typing import Final

from src.domain.models.labeled_choice import LabeledChoice

US_STATES: Final[tuple[str, ...]] = (
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


class LocationAvailability(LabeledChoice):
    yes = "yes", "Yes"
    no = "no", "No"


# Referral session-format axes. Persisted as a list[str] on
# ReferralDetail.session_format: any subset of {in_person, virtual} is
# valid (both = "either", one = single-modality, empty = unspecified).
# The opening / affiliation side keeps its own two-axis shape because
# a practice can legitimately offer both in independent quantities.
class SessionFormat(LabeledChoice):
    in_person = "in_person", "In-person"
    virtual = "virtual", "Virtual"


LOCATION_AVAILABILITY_OPTIONS: Final[tuple[str, ...]] = LocationAvailability.values()
SESSION_FORMATS: Final[tuple[str, ...]] = SessionFormat.values()


# Client age cohorts. Richer than value+label+icon: each member carries a
# singular noun, a plural noun, and a numeric range. The CR card's headline
# composer in `domain/logic/posts/view.py` reads `.singular` + `.range`
# directly ("<noun> <gender> (<range>)"); `.label` is the plural+range form
# ("Children (0–5)") for PA listing rows and the filter dropdown, and
# `.label_singular` is the singular+range form. Multiple members may share an
# icon when they read the same at scan distance (children_0_5 / children_6_10).
class ClientAgeGroup(LabeledChoice):
    singular: str
    plural: str
    range: str
    label_singular: str

    children_0_5 = "children_0_5", "Child", "Children", "0–5", "baby"
    children_6_10 = "children_6_10", "Child", "Children", "6–10", "baby"
    preteens_11_13 = "preteens_11_13", "Preteen", "Preteens", "11–13", "graduation-cap"
    adolescents_14_18 = (
        "adolescents_14_18",
        "Adolescent",
        "Adolescents",
        "14–18",
        "graduation-cap",
    )
    young_adults_19_24 = (
        "young_adults_19_24",
        "Young adult",
        "Young adults",
        "19–24",
        "user",
    )
    adults_25_64 = "adults_25_64", "Adult", "Adults", "25–64", "user"
    older_adults_65_plus = (
        "older_adults_65_plus",
        "Older adult",
        "Older adults",
        "65+",
        "user-round",
    )

    def __new__(
        cls, value: str, singular: str, plural: str, range_: str, icon: str
    ) -> "ClientAgeGroup":
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.singular = singular
        obj.plural = plural
        obj.range = range_
        obj.icon = icon
        obj.label = f"{plural} ({range_})"
        obj.label_singular = f"{singular} ({range_})"
        return obj


CLIENT_AGE_GROUPS: Final[tuple[str, ...]] = ClientAgeGroup.values()


# Spoken-language tokens used by the multi-valued `languages` field on
# both post kinds. Tokens are BCP 47 short codes (ISO-639-1 where
# available); labels are the English display names. Vocabulary widens
# only — `languages` is a JSON-list column with no SQL CHECK against
# array members (Pydantic enforces the wire-side `Literal[*LANGUAGES]`
# in `domain/logic/posts/schema.py`), so adding tokens is non-breaking
# for persisted rows. Expansion beyond en/es tracks the corpus
# evidence surfaced in #1355 / #1358 PR-d (Mandarin-speaking referrals
# plus the next tier of California-relevant languages).
class Language(LabeledChoice):
    en = "en", "English"
    es = "es", "Spanish"
    zh = "zh", "Mandarin"
    yue = "yue", "Cantonese"
    vi = "vi", "Vietnamese"
    tl = "tl", "Tagalog"
    ko = "ko", "Korean"
    ru = "ru", "Russian"
    # Catch-all for a language outside the closed list; paired with the
    # free-text `languages_other_text` column on `ReferralDetail` (the
    # uniform "Other → please specify" pattern, see
    # `posts/conditional_fields.py`).
    other = "other", "Other"


LANGUAGES: Final[tuple[str, ...]] = Language.values()


# Carrier vocabulary for `ClinicianAffiliation.in_network_carriers` and
# `ReferralDetail.insurance_carriers`. Single-sourced so the request
# side (the carriers the patient has) and the provider side (the list
# of carriers the practice accepts) share tokens. Both columns are
# JSON arrays of these tokens; an empty array means "no carrier
# specified" on either side (on the request side this is the natural
# shape when only ``accepts_private_pay`` is true; see
# ``ReferralDetail`` for the payment-path booleans, #1358 PR-e).
class InsuranceCarrier(LabeledChoice):
    aetna = "aetna", "Aetna"
    anthem_bcbs = "anthem_bcbs", "Anthem / BCBS"
    cigna = "cigna", "Cigna"
    kaiser = "kaiser", "Kaiser"
    magellan = "magellan", "Magellan"
    medicare = "medicare", "Medicare"
    medicaid = "medicaid", "Medicaid"
    optum = "optum", "Optum"
    tricare = "tricare", "Tricare"
    united_healthcare = "united_healthcare", "UnitedHealthcare"
    other = "other", "Other"


INSURANCE_CARRIERS: Final[tuple[str, ...]] = InsuranceCarrier.values()


# Day × time-of-day grid for "when are you available". 14 tokens of the
# form `<day>_<part>`. Day order is Mon→Sun (week-of-work convention from
# the form spec); part order is am→pm so the rendered grid reads
# left-to-right (am, pm columns) top-to-bottom (Mon→Sun rows). The two
# axes are their own vocabularies; the combined slot tuple/labels below
# derive from them so the grid stays single-sourced.
#
# `DesiredTimeDay` carries two labels: `.label` is the long form used in
# slot labels (e.g. "Monday AM") and `.short_label` is a compact abbreviation
# (M/T/W/Th/F/Sat/Sun) available for display contexts that need it.
class DesiredTimeDay(LabeledChoice):
    short_label: str

    monday = "monday", "Monday", "M"
    tuesday = "tuesday", "Tuesday", "T"
    wednesday = "wednesday", "Wednesday", "W"
    thursday = "thursday", "Thursday", "Th"
    friday = "friday", "Friday", "F"
    saturday = "saturday", "Saturday", "Sat"
    sunday = "sunday", "Sunday", "Sun"

    def __new__(cls, value: str, label: str, short_label: str) -> "DesiredTimeDay":
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.label = label
        obj.short_label = short_label
        obj.icon = None
        return obj


class DesiredTimePart(LabeledChoice):
    am = "am", "AM"
    pm = "pm", "PM"


DESIRED_TIME_DAYS: Final[tuple[str, ...]] = DesiredTimeDay.values()
DESIRED_TIME_PARTS: Final[tuple[str, ...]] = DesiredTimePart.values()
DESIRED_TIME_SLOTS: Final[tuple[str, ...]] = tuple(
    f"{day}_{part}" for day in DESIRED_TIME_DAYS for part in DESIRED_TIME_PARTS
)


# Service-line categories. The same vocabulary appears on both forms:
# optional `services` on `referral` (empty list allowed) and
# required-min-1 `services` on `opening`. Required-ness
# differs but the value set is shared, so the tuple is single-sourced.
#
# Flat-leaf shape: Therapy splits into individual/group/family leaves;
# Allied health splits into 7 discipline leaves. "Other" is paired
# with a free-text `services_other_text` column on ReferralDetail.
# The form template visually groups therapy + allied-health leaves
# under shared subheadings; the wire shape is flat.
class ReferralService(LabeledChoice):
    medication_management = (
        "medication_management",
        "Psychiatry / medication management",
        "pill",
    )
    therapy_individual = "therapy_individual", "Therapy — Individual", "message-circle"
    therapy_group = "therapy_group", "Therapy — Group", "users"
    therapy_family = "therapy_family", "Therapy — Family", "users-round"
    allied_ot = (
        "allied_ot",
        "Allied health — Occupational Therapy",
        "heart-pulse",
    )
    allied_creative_arts = (
        "allied_creative_arts",
        "Allied health — Creative Arts (Art / Music / Drama)",
        "heart-pulse",
    )
    allied_social_work = (
        "allied_social_work",
        "Allied health — Clinical Social Work",
        "heart-pulse",
    )
    allied_rehab_counseling = (
        "allied_rehab_counseling",
        "Allied health — Rehabilitation Counseling",
        "heart-pulse",
    )
    allied_slp = (
        "allied_slp",
        "Allied health — Speech-Language Pathology",
        "heart-pulse",
    )
    allied_dietetics = (
        "allied_dietetics",
        "Allied health — Dietetics / Nutrition",
        "heart-pulse",
    )
    allied_exercise_physiology = (
        "allied_exercise_physiology",
        "Allied health — Exercise Physiology",
        "heart-pulse",
    )
    other = "other", "Other (describe below)", "more-horizontal"


REFERRAL_SERVICES: Final[tuple[str, ...]] = ReferralService.values()


# Gender identity vocabulary. Single-axis enum that folds trans/cis into
# the value (`female` / `trans_female`) rather than splitting into two
# fields — for the listing row the reader wants one labeled chunk
# ("Gender: Trans woman"), not a parenthesized modifier. `gender_diverse`
# is the umbrella token for genderqueer / agender / two-spirit / etc.
#
# Used as a multi-value list on `opening` (`genders`: the practice
# serves these). Referral no longer carries a gender column.
class Gender(LabeledChoice):
    female = "female", "Female"
    male = "male", "Male"
    non_binary = "non_binary", "Non-binary"
    trans_female = "trans_female", "Trans woman"
    trans_male = "trans_male", "Trans man"
    gender_diverse = "gender_diverse", "Gender-diverse"


GENDERS: Final[tuple[str, ...]] = Gender.values()


# Client pronouns. Multi-value list on `referral` — a client may go by
# more than one set ("she/her, they/them"). Closed enum of atomic sets;
# combinations like "she/they" are expressed by selecting both members
# in the multi-select rather than enumerating every combo as its own
# value. Empty list = "not stated".
class Pronouns(LabeledChoice):
    she_her = "she_her", "she/her"
    he_him = "he_him", "he/him"
    they_them = "they_them", "they/them"
    # Any set outside the closed list; paired with the free-text
    # `pronouns_other_text` column on `ReferralDetail` (the uniform
    # "Other → please specify" pattern, see `posts/conditional_fields.py`).
    other = "other", "Other"


PRONOUNS: Final[tuple[str, ...]] = Pronouns.values()


# --- Display labels for select <option>s --------------------------------
#
# The form-render macro in
# `src/framework/templates/_shared/form_fields.html` looks up labels via these
# `*_LABELS` dicts; missing keys fail at render time. Every dict derives from a
# `LabeledChoice` class (`Cls.labels()`, or a comprehension over the members for
# the richer vocabularies), so the label can't drift from its value.
#
# `US_STATES` deliberately has no label dict — the value (USPS
# abbreviation) is the right user-facing label.

LOCATION_AVAILABILITY_LABELS: Final[dict[str, str]] = LocationAvailability.labels()
SESSION_FORMAT_LABELS: Final[dict[str, str]] = SessionFormat.labels()
# `CLIENT_AGE_GROUPS_BY_KEY` maps each value to its `ClientAgeGroup` member,
# whose `.singular` / `.plural` / `.range` the CR headline builder reads
# directly ("<noun> <gender> (<range>)"). The two label dicts derive the
# ready-to-render plural / singular "<noun> (<range>)" strings.
CLIENT_AGE_GROUPS_BY_KEY: Final[dict[str, ClientAgeGroup]] = {
    m.value: m for m in ClientAgeGroup
}
CLIENT_AGE_GROUP_LABELS: Final[dict[str, str]] = ClientAgeGroup.labels()
CLIENT_AGE_GROUP_LABELS_SINGULAR: Final[dict[str, str]] = {
    m.value: m.label_singular for m in ClientAgeGroup
}
LANGUAGE_LABELS: Final[dict[str, str]] = Language.labels()
INSURANCE_CARRIER_LABELS: Final[dict[str, str]] = InsuranceCarrier.labels()
# Per-axis labels for the desired-times grid. The form-render macro uses these
# Days carry two labels: the long `.label` (read views, slot labels below)
# and the compact `.short_label` abbreviation (M/T/W/Th/F/Sat/Sun).
DESIRED_TIME_DAY_LABELS: Final[dict[str, str]] = DesiredTimeDay.labels()
DESIRED_TIME_DAY_SHORT_LABELS: Final[dict[str, str]] = {
    m.value: m.short_label for m in DesiredTimeDay
}
DESIRED_TIME_PART_LABELS: Final[dict[str, str]] = DesiredTimePart.labels()
# Combined per-token label, e.g. "Monday morning". Used wherever a
# single value is rendered standalone (read views, audit dumps shown
# in admin tooling).
DESIRED_TIME_SLOT_LABELS: Final[dict[str, str]] = {
    f"{day}_{part}": f"{DESIRED_TIME_DAY_LABELS[day]} {DESIRED_TIME_PART_LABELS[part]}"
    for day in DESIRED_TIME_DAYS
    for part in DESIRED_TIME_PARTS
}
REFERRAL_SERVICE_LABELS: Final[dict[str, str]] = ReferralService.labels()
GENDER_LABELS: Final[dict[str, str]] = Gender.labels()
PRONOUNS_LABELS: Final[dict[str, str]] = Pronouns.labels()


# --- Unified insurance posture -----------------------------------------
#
# The two post kinds model "insurance situation" with parallel vocab:
#   * `referral` — an `insurance_carriers` JSON list of
#     `INSURANCE_CARRIERS` tokens (non-empty = in-network; there's no
#     separate boolean) plus the `accepts_private_pay` / `sliding_scale`
#     booleans.
#   * `opening` → linked `Clinician` carries the
#     `in_network_carriers` list (empty = no in-network) plus the
#     `accepts_out_of_network` / `sliding_scale` booleans.
#
# For the listing row we need *one* axis the eye can read at a glance,
# so both shapes collapse to this 3-state posture. The mapping helper
# `insurance_posture_for_post(post)` lives in
# `src/domain/logic/posts/view.py`; it returns `None` when no payment
# signal is set, and the row/facts macros omit the chunk entirely.
# Adding a fourth state means: extend this tuple, extend the labels +
# icons dicts, update the helper, and the row macro picks it up.
class InsurancePosture(LabeledChoice):
    in_network = "in_network", "In-network", "shield-check"
    out_of_network = "out_of_network", "Out-of-network", "shield"
    self_pay = "self_pay", "Self-pay", "dollar-sign"


INSURANCE_POSTURES: Final[tuple[str, ...]] = InsurancePosture.values()
INSURANCE_POSTURE_LABELS: Final[dict[str, str]] = InsurancePosture.labels()


# Affirming-identity vocabulary. Symmetric between the request and provider
# sides of a referral: a `ReferralDetail.affirming_identities` expresses
# the referrer's request (e.g. "queer-affirming please") and a
# `Clinician.affirming_identities` claims an affordance the clinician
# *is* (person-level, invariant across affiliations — moves with the
# person, like credentials, not with a practice posture). Both columns
# are JSON arrays of these tokens; an empty array means "none stated"
# on either side.
#
# Vocabulary derived from the email corpus surfaced in #1355: ~40% of
# referrals and ~40% of broadcasts cite at least one of these.
# `liberation_oriented` is the corpus shorthand for "non-shaming /
# warmth-first / power-aware" framing that providers self-describe with;
# it's the umbrella that lets us avoid a long tail of single-mention
# tokens on day one.
class AffirmingIdentity(LabeledChoice):
    lgbtq = "lgbtq", "LGBTQ-affirming"
    trans = "trans", "Trans-affirming"
    poly = "poly", "Poly-affirming"
    neurodiversity = "neurodiversity", "Neurodiversity-affirming"
    liberation_oriented = "liberation_oriented", "Liberation-oriented"


AFFIRMING_IDENTITIES: Final[tuple[str, ...]] = AffirmingIdentity.values()
AFFIRMING_IDENTITY_LABELS: Final[dict[str, str]] = AffirmingIdentity.labels()


class LicenseType(LabeledChoice):
    lcsw = "lcsw", "Licensed Clinical Social Worker (LCSW)"
    lpc = "lpc", "Licensed Professional Counselor (LPC)"
    lmft = "lmft", "Licensed Marriage and Family Therapist (LMFT)"
    lmhc = "lmhc", "Licensed Mental Health Counselor (LMHC)"
    lcpc = "lcpc", "Licensed Clinical Professional Counselor (LCPC)"
    psyd = "psyd", "Doctor of Psychology (PsyD)"
    phd = "phd", "Doctor of Philosophy (PhD)"
    md = "md", "Medical Doctor (MD)"
    do = "do", "Doctor of Osteopathic Medicine (DO)"
    np = "np", "Nurse Practitioner (NP)"
    pmhnp = "pmhnp", "Psychiatric Mental Health Nurse Practitioner (PMHNP)"
    other = "other", "Other"


LICENSE_TYPES: Final[tuple[str, ...]] = LicenseType.values()
LICENSE_TYPES_LABELS: Final[dict[str, str]] = LicenseType.labels()


class EducationType(LabeledChoice):
    ba_bs = "ba_bs", "Bachelor's Degree (BA/BS)"
    ma_ms = "ma_ms", "Master of Arts/Science (MA/MS)"
    msw = "msw", "Master of Social Work (MSW)"
    phd = "phd", "Doctor of Philosophy (PhD)"
    psyd = "psyd", "Doctor of Psychology (PsyD)"
    md = "md", "Medical Doctor (MD)"
    do = "do", "Doctor of Osteopathic Medicine (DO)"
    edd = "edd", "Doctor of Education (EdD)"
    other = "other", "Other"


EDUCATION_TYPES: Final[tuple[str, ...]] = EducationType.values()
EDUCATION_TYPES_LABELS: Final[dict[str, str]] = EducationType.labels()


class CertificationType(LabeledChoice):
    emdr = "emdr", "EMDR"
    dbt = "dbt", "DBT Certification"
    cbt = "cbt", "CBT Certification"
    gottman_1 = "gottman_1", "Gottman Method Level 1"
    gottman_2 = "gottman_2", "Gottman Method Level 2"
    gottman_3 = "gottman_3", "Gottman Method Level 3"
    cpr = "cpr", "CPR Certified"
    ccatp = "ccatp", "Certified Clinical Anxiety Treatment Professional (CCATP)"
    other = "other", "Other"


CERTIFICATION_TYPES: Final[tuple[str, ...]] = CertificationType.values()
CERTIFICATION_TYPES_LABELS: Final[dict[str, str]] = CertificationType.labels()


# Outcome of a single NPPES verification attempt. `verified` —
# all checks passed; `needs_review` — a soft mismatch worth a human look
# (e.g. NPPES name similarity below threshold); `failed` — a hard
# disqualifier (NPI not in NPPES, or an OIG/LEIE match). One row per
# attempt is appended; the latest row's status is what the UI surfaces.
# Value-only (no display labels) — `.labels()` falls back to the value.
class VerificationStatus(LabeledChoice):
    verified = "verified"
    needs_review = "needs_review"
    failed = "failed"


VERIFICATION_STATUSES: Final[tuple[str, ...]] = VerificationStatus.values()


# NPPES name-match state for an NPI on a `Clinician` (Type-1) or
# `Organization` (Type-2). `none` — no NPI submitted yet; `pending` — the
# row carries an NPI and a worker has yet to resolve it; `matched` — the
# NPPES legal name (or org name + Authorized Official for Type-2) clears
# the similarity threshold; `mismatch` — final state after admin review
# rejects a soft mismatch. Per handoff §10.1, NPPES soft mismatches stay
# `pending` until an admin closes them — they never auto-flip to
# `mismatch`. The icons are Lucide names rendered by the chrome's claim
# badges.
class NpiMatchStatus(LabeledChoice):
    none = "none", "Not submitted", "circle-dashed"
    pending = "pending", "Verifying…", "loader"
    matched = "matched", "Matched", "shield-check"
    mismatch = "mismatch", "Mismatch — in review", "shield-alert"


NPI_MATCH_STATUSES: Final[tuple[str, ...]] = NpiMatchStatus.values()
NPI_MATCH_STATUS_LABELS: Final[dict[str, str]] = NpiMatchStatus.labels()


# Computed-and-stored status of a `ClinicianLicensure`. Derived on write
# from `expiration_date` and `attested_active` (see Phase 8's nightly
# expiry worker) and persisted for query-speed reasons: licensure list
# views surface this directly without recomputing per row. Licensure
# status no longer gates Claim A — see `recompute_clinician_claim`.
class LicenseStatus(LabeledChoice):
    active = "active", "Active", "check"
    expired = "expired", "Expired", "x-circle"
    pending = "pending", "Pending", "loader"


LICENSE_STATUSES: Final[tuple[str, ...]] = LicenseStatus.values()
LICENSE_STATUS_LABELS: Final[dict[str, str]] = LicenseStatus.labels()


# Closed vocab of state transitions that append a `Verification` event
# row. Mirrors handoff §9: every transition that recomputes a claim flag
# writes one row of this `event_type` with the relevant `evidence`
# payload. The pipeline-end NPPES write currently in
# `run_clinician_verification` is `npi_resolved`; admin overrides go
# through `admin_verify`/`admin_suspend`; org authority transitions go
# through `authority_proven` / `authority_revoked` / `role_set`. Value-
# only — `.labels()` falls back to the storage value.
class VerificationEventType(LabeledChoice):
    npi_submitted = "npi_submitted"
    npi_resolved = "npi_resolved"
    license_attested = "license_attested"
    license_expired = "license_expired"
    authority_proven = "authority_proven"
    authority_revoked = "authority_revoked"
    role_set = "role_set"
    admin_verify = "admin_verify"
    admin_suspend = "admin_suspend"
    email_confirmed = "email_confirmed"


VERIFICATION_EVENT_TYPES: Final[tuple[str, ...]] = VerificationEventType.values()


# Discriminator vocab for the polymorphic `Verification` row. Drives the
# CHECK ensuring exactly one of (`clinician_id`, `org_id`) is set.
class VerificationSubjectType(LabeledChoice):
    clinician = "clinician"
    organization = "organization"


VERIFICATION_SUBJECT_TYPES: Final[tuple[str, ...]] = VerificationSubjectType.values()


# Role a user plays within an `OrgRepresentation` (User↔Org link).
# Per handoff §5.3: `coordinator` is the base role (can post program
# intakes / org-attributed referrals); `admin` adds the ability to
# approve additional reps (`rep_approval` path); `owner` is the
# first-claim authority (typically the solo practitioner whose name
# matches the org's NPPES Authorized Official).
class OrgRepresentationRole(LabeledChoice):
    coordinator = "coordinator", "Coordinator", "clipboard-list"
    admin = "admin", "Admin", "shield"
    owner = "owner", "Owner", "building"


ORG_REPRESENTATION_ROLES: Final[tuple[str, ...]] = OrgRepresentationRole.values()
ORG_REPRESENTATION_ROLE_LABELS: Final[dict[str, str]] = OrgRepresentationRole.labels()


# How a user proves they may act for an organization. Per handoff §6:
# `authorized_official` — NPPES Authorized-Official name-match (auto;
# covers most solos & small practices); `domain_email` — verified email
# at the org's domain (v1 stub); `rep_approval` — an existing verified
# rep approves a new one (cheap, scales group practices); `admin_review`
# — fallback when neither auto-path applies.
class AuthorityMethod(LabeledChoice):
    authorized_official = (
        "authorized_official",
        "NPPES Authorized Official match",
    )
    domain_email = "domain_email", "Verified org-domain email"
    rep_approval = "rep_approval", "Approved by an existing rep"
    admin_review = "admin_review", "Admin review"


AUTHORITY_METHODS: Final[tuple[str, ...]] = AuthorityMethod.values()
AUTHORITY_METHOD_LABELS: Final[dict[str, str]] = AuthorityMethod.labels()


# Status of an `OrgRepresentation.authority_status`. `pending` is the
# default at insert; the `authority` state axis (admin override) flips
# to `verified` or `rejected`. Revocation archives the row via
# `archived_at` rather than deleting (handoff §10.8).
class AuthorityStatus(LabeledChoice):
    pending = "pending", "Pending", "loader"
    verified = "verified", "Verified", "shield-check"
    rejected = "rejected", "Rejected", "shield-alert"


AUTHORITY_STATUSES: Final[tuple[str, ...]] = AuthorityStatus.values()
AUTHORITY_STATUS_LABELS: Final[dict[str, str]] = AuthorityStatus.labels()


# `AdminNote` vocabularies — written only by the admin's Datasette
# "Add a note" query (`src/domain/logic/admin_data/`), so the DB CHECKs are the only
# validation these values get. `subject_type` names what the note is
# about; `action` is what the admin did; `value` is the structured
# outcome for the two actions that have one (a check-in reply mirrors
# the check-in email's "Yes / Not yet / No"; a verdict is the
# good / not-good call that `post_outcomes` reads).
class AdminNoteSubject(LabeledChoice):
    connection = "connection", "Connection"
    post = "post", "Post"
    member = "member", "Member"


class AdminNoteAction(LabeledChoice):
    reviewed = "reviewed", "Reviewed"
    check_in_sent = "check_in_sent", "Check-in sent"
    check_in_reply = "check_in_reply", "Check-in reply"
    verdict = "verdict", "Verdict"


class CheckInReply(LabeledChoice):
    yes = "yes", "Yes"
    not_yet = "not_yet", "Not yet"
    no = "no", "No"


class ConnectionVerdict(LabeledChoice):
    good = "good", "Good"
    not_good = "not_good", "Not good"


ADMIN_NOTE_SUBJECTS: Final[tuple[str, ...]] = AdminNoteSubject.values()
ADMIN_NOTE_ACTIONS: Final[tuple[str, ...]] = AdminNoteAction.values()
CHECK_IN_REPLIES: Final[tuple[str, ...]] = CheckInReply.values()
CONNECTION_VERDICTS: Final[tuple[str, ...]] = ConnectionVerdict.values()


def check_in_tuple_sql(column: str, values: tuple[str, ...]) -> str:
    """SQL fragment for a `column IN (...)` CHECK constraint, rendered
    from a tuple. Used by per-kind detail tables so the DB-level
    vocabulary stays in lockstep with the Python tuples above. Mirrors
    the `POST_KINDS.check_sql()` pattern used by the parent `posts` table.

    Uses SQL single-quote string literals with `'` doubled per SQL
    standard. `repr()` would work for the current ASCII-only enum
    values but switches to double-quoted form when a value contains
    `'`, which SQLite parses as an identifier rather than a string —
    so it's not safe for arbitrary future values."""
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return f"{column} IN ({quoted})"


def named_check_in(
    table: str, column: str, values: tuple[str, ...]
) -> "CheckConstraint":
    """`column IN (values)` CHECK named `ck_<table>_<column>`.

    Centralizes the per-model `_ck` boilerplate every entity using a
    controlled-vocabulary column was restating. Models import this
    directly instead of redeclaring a local closure over `_TABLE`.
    """
    from sqlalchemy import CheckConstraint

    return CheckConstraint(
        check_in_tuple_sql(column, values),
        name=f"ck_{table}_{column}",
    )
