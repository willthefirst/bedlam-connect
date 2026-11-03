"""Domain vocabularies the seed generator draws from for free-text /
proper-noun columns. **Not** schema-enforced (the schema's controlled
vocabularies live in `src/domain/models/enums.py`); these are realism
scaffolding for fields the CHECK constraint can't constrain.

The load-bearing export is `COLUMN_VOCAB` — a column-name → strategy
dict consulted by `generators.py` when the generic generator hits a
free-text (or JSON-list, or numeric-shape) column. If a column name
isn't here AND isn't CHECK-constrained AND isn't in `PLACEHOLDER_OK`,
the drift lint fails (`lint_coverage.py`) — that's how we keep the
generator producing believable values as the schema grows.

How to extend when a model changes:

  1. New CHECK-constrained Text column: nothing to do. `generators.py`
     reads the CHECK values via `check_registry.py` and round-robins.
  2. New free-text column with a domain-meaningful name
     (`institution`, `cost`, `slogan`): add an entry to `COLUMN_VOCAB`.
  3. New free-text column where `<column_name>_<index>` is acceptable
     (placeholder, opaque, only used in admin tooling): add the column
     name to `PLACEHOLDER_OK`.
  4. New JSON-list column referencing an enum: add an entry to
     `JSON_LIST_SOURCE` mapping the column name → the enum tuple it
     should subset over.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from src.domain.models.enums import (
    AFFIRMING_IDENTITIES,
    CERTIFICATION_TYPES,
    CLIENT_AGE_GROUPS,
    DESIRED_TIME_SLOTS,
    EDUCATION_TYPES,
    GENDERS,
    INSURANCE_CARRIERS,
    LANGUAGES,
    LICENSE_TYPES,
    PRONOUNS,
    REFERRAL_SERVICES,
    SESSION_FORMATS,
    US_STATES,
)

from .rng import SeededRandom

# --- Name pools --------------------------------------------------------
# Culturally mixed so generated clinicians don't read as one monoculture.
# Order is irrelevant; round-robin picks index % len.
FIRST_NAMES: Final[tuple[str, ...]] = (
    "Aaliyah",
    "Aiden",
    "Alejandro",
    "Amara",
    "Amelia",
    "Anika",
    "Arjun",
    "Ava",
    "Beatriz",
    "Caleb",
    "Camila",
    "Carlos",
    "Chen",
    "Chloe",
    "Daniel",
    "Diego",
    "Elena",
    "Eli",
    "Elijah",
    "Emma",
    "Esther",
    "Ethan",
    "Fatima",
    "Gabriel",
    "Grace",
    "Hannah",
    "Hiro",
    "Ibrahim",
    "Imani",
    "Isabella",
    "Jamal",
    "James",
    "Jasmine",
    "Jin",
    "Julia",
    "Kai",
    "Kenji",
    "Khadija",
    "Lakshmi",
    "Layla",
    "Leila",
    "Liam",
    "Lin",
    "Lucas",
    "Maria",
    "Mateo",
    "Maya",
    "Mei",
    "Mohammed",
    "Naomi",
    "Nia",
    "Nikhil",
    "Noah",
    "Olivia",
    "Omar",
    "Patel",
    "Priya",
    "Rafael",
    "Raj",
    "Rashida",
    "Ravi",
    "Rebecca",
    "Rohan",
    "Rosa",
    "Samir",
    "Sara",
    "Sebastian",
    "Sofia",
    "Sophie",
    "Tariq",
    "Tomas",
    "Uma",
    "Valentina",
    "Wei",
    "Xavier",
    "Yasmin",
    "Yuki",
    "Zara",
    "Zoe",
)
LAST_NAMES: Final[tuple[str, ...]] = (
    "Adeyemi",
    "Andersen",
    "Bauer",
    "Brennan",
    "Castillo",
    "Chen",
    "Cohen",
    "Davies",
    "Diaz",
    "Eriksson",
    "Flores",
    "Foster",
    "Garcia",
    "Goldberg",
    "Gomez",
    "Gupta",
    "Hassan",
    "Hernandez",
    "Hoffman",
    "Iyer",
    "Jackson",
    "Jensen",
    "Johnson",
    "Kang",
    "Khan",
    "Kim",
    "Kowalski",
    "Lee",
    "Liu",
    "Lopez",
    "Mahmoud",
    "Martin",
    "Martinez",
    "Mehta",
    "Mitchell",
    "Morales",
    "Murphy",
    "Nakamura",
    "Nguyen",
    "Novak",
    "Okafor",
    "Okonkwo",
    "O'Brien",
    "Patel",
    "Perez",
    "Petrov",
    "Reyes",
    "Rivera",
    "Rodriguez",
    "Romano",
    "Rossi",
    "Sanchez",
    "Santos",
    "Schmidt",
    "Shah",
    "Shapiro",
    "Singh",
    "Smith",
    "Sullivan",
    "Tanaka",
    "Taylor",
    "Thompson",
    "Torres",
    "Tran",
    "Turner",
    "Vargas",
    "Vasquez",
    "Wang",
    "Williams",
    "Wong",
    "Wright",
    "Yamamoto",
    "Yang",
    "Yates",
    "Zhang",
    "Zheng",
)

# --- Geography --------------------------------------------------------
# 3-5 real cities for the highest-population US states; "Springfield"
# fallback for the rest so every state still resolves to a city.
CITIES_BY_STATE: Final[dict[str, tuple[str, ...]]] = {
    "CA": ("Los Angeles", "San Francisco", "San Diego", "Sacramento", "Oakland"),
    "TX": ("Houston", "Austin", "Dallas", "San Antonio", "Fort Worth"),
    "NY": ("New York", "Buffalo", "Rochester", "Albany", "Syracuse"),
    "FL": ("Miami", "Orlando", "Tampa", "Jacksonville", "Tallahassee"),
    "IL": ("Chicago", "Springfield", "Naperville", "Aurora"),
    "PA": ("Philadelphia", "Pittsburgh", "Allentown", "Erie"),
    "OH": ("Columbus", "Cleveland", "Cincinnati", "Toledo"),
    "GA": ("Atlanta", "Savannah", "Augusta", "Macon"),
    "NC": ("Charlotte", "Raleigh", "Greensboro", "Durham"),
    "MI": ("Detroit", "Grand Rapids", "Ann Arbor", "Lansing"),
    "NJ": ("Newark", "Jersey City", "Paterson", "Trenton"),
    "VA": ("Richmond", "Virginia Beach", "Norfolk", "Arlington"),
    "WA": ("Seattle", "Tacoma", "Spokane", "Olympia"),
    "AZ": ("Phoenix", "Tucson", "Mesa", "Scottsdale"),
    "MA": ("Boston", "Worcester", "Cambridge", "Springfield"),
    "TN": ("Nashville", "Memphis", "Knoxville", "Chattanooga"),
    "IN": ("Indianapolis", "Fort Wayne", "Evansville", "Bloomington"),
    "MO": ("St. Louis", "Kansas City", "Springfield", "Columbia"),
    "MD": ("Baltimore", "Rockville", "Frederick", "Annapolis"),
    "WI": ("Milwaukee", "Madison", "Green Bay", "Kenosha"),
    "CO": ("Denver", "Boulder", "Aurora", "Fort Collins"),
    "MN": ("Minneapolis", "St. Paul", "Rochester", "Duluth"),
    "OR": ("Portland", "Eugene", "Salem", "Bend"),
    "NV": ("Las Vegas", "Reno", "Henderson", "Carson City"),
}

# 2-digit ZIP prefix per state, padded out to a 5-digit ZIP in the
# generator. Source: USPS state-ZIP ranges (first 2 digits). Fallback
# `010` covers any state missing here (a benign Massachusetts ZIP).
ZIP_PREFIX_BY_STATE: Final[dict[str, str]] = {
    "AL": "352",
    "AK": "995",
    "AZ": "850",
    "AR": "720",
    "CA": "940",
    "CO": "802",
    "CT": "060",
    "DE": "197",
    "DC": "200",
    "FL": "331",
    "GA": "303",
    "HI": "967",
    "ID": "832",
    "IL": "606",
    "IN": "462",
    "IA": "501",
    "KS": "660",
    "KY": "402",
    "LA": "701",
    "ME": "041",
    "MD": "212",
    "MA": "021",
    "MI": "482",
    "MN": "554",
    "MS": "390",
    "MO": "631",
    "MT": "591",
    "NE": "681",
    "NV": "891",
    "NH": "032",
    "NJ": "070",
    "NM": "871",
    "NY": "100",
    "NC": "282",
    "ND": "585",
    "OH": "432",
    "OK": "731",
    "OR": "972",
    "PA": "191",
    "RI": "029",
    "SC": "292",
    "SD": "571",
    "TN": "372",
    "TX": "770",
    "UT": "841",
    "VT": "054",
    "VA": "232",
    "WA": "981",
    "WV": "253",
    "WI": "532",
    "WY": "820",
}

# --- Practice / institution names -------------------------------------
PRACTICE_ADJECTIVES: Final[tuple[str, ...]] = (
    "Greenfield",
    "Lakeside",
    "Mountainview",
    "Riverside",
    "Sunset",
    "Beacon Hill",
    "North Loop",
    "Cascade",
    "Evergreen",
    "Harborlight",
    "Meadowbrook",
    "Stonebridge",
    "Willow Creek",
    "Oakwood",
    "Cedar",
    "Pacific",
    "Atlantic",
    "Heritage",
    "Pinecrest",
    "Hilltop",
)
PRACTICE_NATURE: Final[tuple[str, ...]] = (
    "Wellness",
    "Behavioral Health",
    "Counseling",
    "Therapy",
    "Psychiatry",
    "Mental Health",
    "Family",
    "Recovery",
    "Mind",
    "Wellbeing",
)
PRACTICE_NOUN: Final[tuple[str, ...]] = (
    "Clinic",
    "Group",
    "Associates",
    "Collective",
    "Center",
    "Practice",
    "Partners",
    "Institute",
    "Services",
    "Network",
)

INSTITUTIONS: Final[tuple[str, ...]] = (
    "Stanford University",
    "Harvard Medical School",
    "Johns Hopkins University",
    "UC Berkeley",
    "UCLA",
    "Yale University",
    "Columbia University",
    "University of Michigan",
    "NYU Silver School of Social Work",
    "Boston University",
    "University of Chicago",
    "USC",
    "University of Washington",
    "UC San Francisco School of Medicine",
    "Penn State",
    "University of Pennsylvania",
    "MIT",
    "Princeton University",
    "Duke University",
    "Northwestern University",
    "Smith College",
    "Pepperdine University",
    "Walden University",
    "University of Minnesota",
    "University of Texas",
    "Tufts University",
    "University of North Carolina",
    "Georgetown University",
    "Vanderbilt University",
    "Western University of Health Sciences",
)
CERTIFYING_BODIES: Final[tuple[str, ...]] = (
    "EMDR International Association",
    "Behavioral Tech",
    "The Gottman Institute",
    "Beck Institute",
    "American Red Cross",
    "American Heart Association",
    "Evergreen Certifications",
    "Linehan Board",
    "International OCD Foundation",
    "Trauma Center at JRI",
)

# --- Clinical free-text templates -------------------------------------
# Mad-Libs templates parameterized by age_group + condition + insurance
# context. Combined with `CONDITIONS` in the generator so each row gets
# a unique, clinically-believable description without copy-paste.
CONDITIONS: Final[tuple[str, ...]] = (
    "complex PTSD",
    "selective mutism",
    "OCD",
    "postpartum depression",
    "panic disorder",
    "social anxiety",
    "treatment-resistant depression",
    "bipolar II",
    "ADHD",
    "autism spectrum (Level 1)",
    "eating disorder",
    "self-harm and suicidality",
    "substance use",
    "grief and bereavement",
    "borderline personality patterns",
    "school refusal",
    "perinatal mood concerns",
    "trauma history",
    "anger management",
    "executive functioning difficulties",
    "chronic pain co-occurring with depression",
    "gender dysphoria",
    "obsessive ruminations",
    "phase-of-life adjustment",
    "high-acuity DBT-target behaviors",
)
MODALITIES_FREETEXT: Final[tuple[str, ...]] = (
    "CBT",
    "DBT",
    "ACT",
    "EMDR",
    "IFS",
    "Psychodynamic",
    "Trauma-focused CBT",
    "Mentalization-based therapy",
    "Family systems",
    "Motivational interviewing",
    "Gottman Method",
    "Mindfulness-based",
    "Exposure and response prevention",
)
# No post kind carries a poster-set `subject` column — every title is
# derived (`post_feed_headline`: demographics for referrals, org name for
# openings, program name for intakes). `INTAKE_SUBJECTS` survives only as a
# free-text description source for the Program seed override.
INTAKE_SUBJECTS: Final[tuple[str, ...]] = (
    "Program intake — adolescents, DBT",
    "IOP accepting referrals — adults, anxiety/depression",
    "Residential: youth 12–17, trauma-informed",
    "PHP cohort starting soon — adults, psychosis stabilization",
)
REFERRAL_TEMPLATES: Final[tuple[str, ...]] = (
    "Looking for a clinician for a {age_descriptor} with {condition}. "
    "{insurance_note}",
    "Referring out a {age_descriptor} presenting with {condition}. "
    "Open to {modality}; {insurance_note}",
    "{age_descriptor} client needs ongoing {service_word} for {condition}. "
    "{insurance_note}",
    "Seeking a {modality}-trained therapist for a {age_descriptor} with "
    "{condition}. {insurance_note}",
    "{age_descriptor} with {condition} stepping down from higher level of "
    "care. {insurance_note}",
)
OPENING_TEMPLATES: Final[tuple[str, ...]] = (
    "Accepting new clients for {service_word} focused on {condition}. "
    "Practice serves {age_descriptor} clients.",
    "Openings available in our {modality} caseload — clients presenting "
    "with {condition} preferred. {age_descriptor} focus.",
    "New referrals welcomed for {service_word}. {modality} orientation; "
    "{age_descriptor} specialty.",
    "Immediate availability for {age_descriptor} clients seeking "
    "{service_word}. Special interest in {condition}.",
)
INTAKE_TEMPLATES: Final[tuple[str, ...]] = (
    "Program currently accepting intake for {age_descriptor} with "
    "{condition}. {modality}-informed.",
    "Rolling admissions for our {service_word} program. {age_descriptor} "
    "focus; clients with {condition} are a strong fit.",
    "Cohort opening soon. {age_descriptor} program; {modality} curriculum; "
    "appropriate for {condition}.",
)
AGE_DESCRIPTORS: Final[dict[str, str]] = {
    "children_0_5": "young child",
    "children_6_10": "school-age child",
    "preteens_11_13": "preteen",
    "adolescents_14_18": "adolescent",
    "young_adults_19_24": "young adult",
    "adults_25_64": "adult",
    "older_adults_65_plus": "older adult",
}
# Natural-prose phrase per service, drawn for the `{service_word}` slot in
# the description templates. Keys track the current `REFERRAL_SERVICES`
# vocabulary (the old `psychotherapy` / `case_management` / `couples_therapy`
# tokens are gone); only the prose values reach the seed text.
SERVICE_WORDS: Final[dict[str, str]] = {
    "medication_management": "medication management",
    "therapy_individual": "individual therapy",
    "therapy_group": "group therapy",
    "therapy_family": "family therapy",
    "allied_social_work": "clinical social work",
    "allied_ot": "occupational therapy",
    "allied_creative_arts": "creative arts therapy",
}
INSURANCE_NOTES: Final[tuple[str, ...]] = (
    "Aetna preferred but flexible.",
    "Medicaid required.",
    "Self-pay; budget is flexible.",
    "BCBS preferred.",
    "Looking for in-network with Kaiser.",
    "Out-of-network OK if sliding scale.",
    "Tricare required.",
    "Open to most major commercial insurance.",
)

# --- Cost templates ---------------------------------------------------
COST_TEMPLATES: Final[tuple[str, ...]] = (
    "$120 per session",
    "$80–$200 sliding",
    "$200 per session",
    "$95 per session",
    "$150–$250 sliding",
    "$300 per session",
    "$60 sliding minimum",
    "$180 per session",
)

# --- Free-text fragments for posts ------------------------------------
WEBSITE_DOMAINS: Final[tuple[str, ...]] = (
    "example.com",
    "example.org",
    "example.net",
    "wellness-example.com",
    "behavioral-example.org",
)
REFERRAL_INSTRUCTIONS: Final[tuple[str, ...]] = (
    "Email intake@example.com with the referred client's first name, age, "
    "and current level of care.",
    "Call the front desk to schedule an intake screening.",
    "Use the contact form on our website; we respond within 2 business days.",
    "Fax referral packet to (555) 555-0100.",
    "Submit through our online referral portal; we triage daily.",
)
SCHEDULE_TEXT_TEMPLATES: Final[tuple[str, ...]] = (
    "M-F 9am-5pm",
    "Tue/Thu evenings only",
    "Rolling cohorts every 4 weeks",
    "Summer cohort: Jun 18 - Aug 9",
    "Mornings only; 8am-12pm",
    "Limited Friday slots",
)


# --- Strategy types ---------------------------------------------------
# A COLUMN_VOCAB entry is either a callable `(rng, index) -> value` or a
# tuple of literal values the generator will round-robin over. Callables
# get index for deterministic indexing.
ColumnStrategy = Callable[[SeededRandom, int], object]


def _round_robin(values: tuple[object, ...]) -> ColumnStrategy:
    return lambda rng, i: rng.round_robin(values, i)


def _npi_strategy(rng: SeededRandom, index: int) -> str:
    """NPPES-shape NPI: exactly 10 ASCII digits. The DB CHECK
    `ck_clinicians_npi_format` requires this exact shape."""
    return "".join(str(rng.int(0, 9)) for _ in range(10))


def _license_number(rng: SeededRandom, index: int) -> str:
    prefix = rng.choice(("LIC", "LCS", "LMFT", "MD", "NP", "PMHNP", "PSY"))
    return f"{prefix}-{rng.int(10000, 99999)}"


def _email_clinician(rng: SeededRandom, index: int) -> str:
    return f"clinician_{index:03d}@example.com"


def _username_clinician(rng: SeededRandom, index: int) -> str:
    return f"clinician_{index:03d}"


def _website(rng: SeededRandom, index: int) -> str:
    slug = rng.choice(FIRST_NAMES).lower()
    return f"https://{slug}.{rng.choice(WEBSITE_DOMAINS)}"


def _zip_for_state(rng: SeededRandom, state: str) -> str:
    prefix = ZIP_PREFIX_BY_STATE.get(state, "010")
    return f"{prefix}{rng.int(10, 99)}"


def _month_completed(rng: SeededRandom, index: int) -> str:
    year = rng.int(1990, 2024)
    month = rng.int(1, 12)
    return f"{year}-{month:02d}"


def _location_city_fallback(rng: SeededRandom, index: int) -> str:
    """Fallback when the column isn't being filled via the state-aware
    path in `generators.py` (e.g. when a model has `location_city`
    without `location_state`). Picks any real city — state context
    isn't available so the city/state pair won't be coherent, but the
    value is still believable."""
    state = rng.round_robin(tuple(CITIES_BY_STATE.keys()), index)
    return rng.choice(CITIES_BY_STATE[state])


def _location_zip_fallback(rng: SeededRandom, index: int) -> str:
    """Fallback ZIP — same caveat as `_location_city_fallback`."""
    state = rng.round_robin(tuple(ZIP_PREFIX_BY_STATE.keys()), index)
    return _zip_for_state(rng, state)


def _description_fallback(rng: SeededRandom, index: int) -> str:
    """Generic description used when the per-kind renderer isn't in
    scope — keeps the value believable so the drift lint can stay
    strict about coverage. Late-binds to `render_opening_description`
    so the COLUMN_VOCAB dict literal below can resolve at module-load
    time (the renderer is defined further down)."""
    return render_opening_description(rng, index)


def _name_fallback(rng: SeededRandom, index: int) -> str:
    """Late-binding wrapper around `practice_name` — same module-order
    rationale as `_description_fallback`."""
    return practice_name(rng, index)


# --- The strategy registry --------------------------------------------
# Maps column NAME (not (model, column)) → strategy. The generic
# generator consults this when a column is free-text and has no CHECK.
# Adding a new column with one of these names → no edit needed here.
# Adding a new column with a different name → add an entry here OR add
# the name to `PLACEHOLDER_OK` below.
COLUMN_VOCAB: Final[dict[str, ColumnStrategy]] = {
    "first_name": _round_robin(FIRST_NAMES),
    "last_name": _round_robin(LAST_NAMES),
    "institution": _round_robin(INSTITUTIONS),
    "certifying_body": _round_robin(CERTIFYING_BODIES),
    "npi": _npi_strategy,
    "license_number": _license_number,
    "email": _email_clinician,
    "username": _username_clinician,
    "website": _website,
    "cost": _round_robin(COST_TEMPLATES),
    "schedule_text": _round_robin(SCHEDULE_TEXT_TEMPLATES),
    "referral_instructions": _round_robin(REFERRAL_INSTRUCTIONS),
    "month_completed": _month_completed,
    # Location columns: the state-aware path in `generators.py` handles
    # zip via `_zip_for_state(state)`. These fallbacks cover the case
    # where a future model has `location_city` / `location_zip` without
    # a sibling `location_state` column.
    "location_city": _location_city_fallback,
    "location_zip": _location_zip_fallback,
    # Free-text names + descriptions. Overrides usually produce these
    # via the kind-aware renderers (`render_*_description`,
    # `practice_name`, `program_name`); these entries are the
    # generic fallback so the drift lint can stay strict — defense-in-
    # depth means the generator works even if an override stops
    # populating a column.
    "name": _name_fallback,
    "description": _description_fallback,
}

# Columns whose values the generator may auto-fill with
# `<column_name>_<index>` placeholders. Use sparingly — only for free-
# text columns where a realistic value isn't important for UI demos.
# The drift lint refuses to ship a new uncovered free-text column
# unless its name appears here or in `COLUMN_VOCAB`.
PLACEHOLDER_OK: Final[frozenset[str]] = frozenset(
    {
        # `audit_log` is skipped by the runner (`SKIP_TABLES`) and is
        # framework-owned (`src/framework/audit/log.py`); rows there
        # are appended in response to *other* writes. The lint still
        # walks every model so these columns surface; declaring them
        # placeholder-OK acknowledges we deliberately don't seed
        # audit rows.
        "resource_type",
        "action",
        # `admin_notes.value` / `.note` are filled by the `admin_notes`
        # override, never the generic generator; `value`'s
        # action-dependent CHECK is cross-column, which the per-column
        # lint can't resolve, so both are acknowledged here.
        "value",
        "note",
        # Org's cached NPPES "Authorized Official" name (free text from
        # NPPES). Seed data doesn't simulate NPPES so a placeholder
        # value here is meaningless — the column is only populated by
        # `run_org_verification` against real NPPES responses.
        "authorized_official_name",
        # `verifications.subject_type` is covered by its own IN-CHECK
        # (closed vocab via `VerificationSubjectType`); the polymorphic
        # subject-shape CHECK is a cross-column XOR that the
        # `verifications` seed override satisfies by construction. The
        # per-column drift lint sees only the first lowercase word in
        # the shape CHECK SQL (`clinician_id`, after skipping
        # `(subject_type` which has a non-alnum char), so we
        # acknowledge it here. `clinician_id` is an FK populated from
        # the parent-row pool, not via COLUMN_VOCAB.
        "clinician_id",
        # Free-text fields on `referral_details` added in the referral-form
        # additive PR. A placeholder string is fine for these (the column
        # only matters for the form / display); listing them here keeps the
        # seed lint quiet without committing the generator to a synthetic
        # vocabulary that drifts from the human-authored form copy.
        "insurance_carriers_other_text",
        "services_other_text",
        "languages_other_text",
        "pronouns_other_text",
    }
)

# Seed vocabulary for `clinical_niches` — free-form on the wire (#1358
# PR-c) but the seed generator still needs a believable subset to draw
# from. Sourced from the referral-email corpus in #1355; promote into a
# `Literal[*ENUM]` once usage stabilizes.
CLINICAL_NICHES_SEED: Final[tuple[str, ...]] = (
    "DGBI",
    "catatonia",
    "ADHD in women",
    "complex trauma",
    "psychedelic-knowledgeable",
    "minor consent",
    "perinatal mood",
    "eating disorders",
    "OCD",
    "couples and family",
    "first-episode psychosis",
    "TBI",
)

# JSON-list columns → which enum to subset over. Most JSON columns
# carry a vocabulary referenced from `enums.py`; the generator can't
# infer the link from the column itself, so we declare it explicitly.
JSON_LIST_SOURCE: Final[dict[str, tuple[str, ...]]] = {
    "age_groups": CLIENT_AGE_GROUPS,
    "languages": LANGUAGES,
    "services": REFERRAL_SERVICES,
    "desired_times": DESIRED_TIME_SLOTS,
    "genders": GENDERS,
    "in_network_carriers": INSURANCE_CARRIERS,
    # `ReferralDetail.insurance_carriers` — request-side carrier
    # multi-select (#1358 PR-e). Symmetric vocab to
    # `in_network_carriers` on the provider side.
    "insurance_carriers": INSURANCE_CARRIERS,
    "affirming_identities": AFFIRMING_IDENTITIES,
    "pronouns": PRONOUNS,
    "session_format": SESSION_FORMATS,
    "acceptable_license_types": LICENSE_TYPES,
    # Free-form on the wire — the seed subset above is realism only,
    # not a closed vocabulary. See `CLINICAL_NICHES_SEED` above.
    "clinical_niches": CLINICAL_NICHES_SEED,
    "flags": (  # Verification.flags — free-form bag of strings
        "name_mismatch",
        "nppes_inactive",
        "oig_excluded",
        "no_npi",
        "nppes_npi_not_found",
        "nppes_name_mismatch",
    ),
}


# --- Description templating ------------------------------------------
def render_referral_description(rng: SeededRandom, index: int) -> str:
    template = rng.round_robin(REFERRAL_TEMPLATES, index)
    age_token = rng.round_robin(CLIENT_AGE_GROUPS, index)
    return template.format(
        age_descriptor=AGE_DESCRIPTORS[age_token],
        condition=rng.round_robin(CONDITIONS, index),
        modality=rng.round_robin(MODALITIES_FREETEXT, index),
        service_word=rng.round_robin(tuple(SERVICE_WORDS.values()), index),
        insurance_note=rng.round_robin(INSURANCE_NOTES, index),
    )


def render_opening_description(rng: SeededRandom, index: int) -> str:
    template = rng.round_robin(OPENING_TEMPLATES, index)
    age_token = rng.round_robin(CLIENT_AGE_GROUPS, index)
    return template.format(
        age_descriptor=AGE_DESCRIPTORS[age_token] + "s",
        condition=rng.round_robin(CONDITIONS, index),
        modality=rng.round_robin(MODALITIES_FREETEXT, index),
        service_word=rng.round_robin(tuple(SERVICE_WORDS.values()), index),
    )


def render_intake_description(rng: SeededRandom, index: int) -> str:
    template = rng.round_robin(INTAKE_TEMPLATES, index)
    age_token = rng.round_robin(CLIENT_AGE_GROUPS, index)
    return template.format(
        age_descriptor=AGE_DESCRIPTORS[age_token] + "s",
        condition=rng.round_robin(CONDITIONS, index),
        modality=rng.round_robin(MODALITIES_FREETEXT, index),
        service_word=rng.round_robin(tuple(SERVICE_WORDS.values()), index),
    )


def practice_name(rng: SeededRandom, index: int) -> str:
    adj = rng.round_robin(PRACTICE_ADJECTIVES, index)
    nature = rng.round_robin(PRACTICE_NATURE, index // len(PRACTICE_ADJECTIVES))
    noun = rng.round_robin(
        PRACTICE_NOUN, index // (len(PRACTICE_ADJECTIVES) * len(PRACTICE_NATURE))
    )
    return f"{adj} {nature} {noun}"


def program_name(rng: SeededRandom, index: int) -> str:
    base = rng.round_robin(PRACTICE_NATURE, index)
    return f"{base} Intensive Program #{index:02d}"


# Re-export for convenience so generators.py can import everything from one
# place.
__all__ = [
    "COLUMN_VOCAB",
    "PLACEHOLDER_OK",
    "JSON_LIST_SOURCE",
    "FIRST_NAMES",
    "LAST_NAMES",
    "CITIES_BY_STATE",
    "ZIP_PREFIX_BY_STATE",
    "INSTITUTIONS",
    "CERTIFYING_BODIES",
    "MODALITIES_FREETEXT",
    "AGE_DESCRIPTORS",
    "SERVICE_WORDS",
    "_zip_for_state",
    "render_referral_description",
    "render_opening_description",
    "render_intake_description",
    "practice_name",
    "program_name",
    "US_STATES",
    "EDUCATION_TYPES",
    "LICENSE_TYPES",
    "CERTIFICATION_TYPES",
]
