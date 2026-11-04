"""URL invariants for the unified `/posts` whole-supertype face.

`Post` is a polymorphic supertype with three kinds (`referral`,
`clinician_opening`, `program_intake`) exposed under a single URL
family. This module pins the cross-kind invariants the framework's
whole-supertype dispatch buys us:

  - the list / search / form-picker routes respond 200;
  - `/posts/form` (no `?kind=`) renders the picker; `/posts/form?kind=X`
    renders the kind-specific create form;
  - the `kind` filter is exposed on `/posts/search` so a viewer can
    narrow the unified feed to one kind;
  - `?kind=<value>` on the list URL narrows results to that kind;
  - owner authz invariants survive the consolidation (non-owner can't
    patch/delete; admin can);
  - the `form_error_render` opt-in is wired end-to-end for each kind.

Per-kind detail-rendering assertions (which DOM elements a referral
card surfaces vs. an opening card vs. an intake card) are the long
tail and live in the kind-specific template / card-view tests.
"""

import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.posts.sections import (
    REFERRAL_SECTION_ORDER,
    REFERRAL_SECTIONS,
)
from src.domain.models import Clinician, Organization, Post, Program
from src.domain.models.enums import CLIENT_AGE_GROUP_LABELS_SINGULAR
from src.domain.models.org_representations.org_representation import OrgRepresentation
from tests.helpers import (
    create_test_user,
    make_clinician,
    make_clinician_with_org,
    make_intake_detail,
    make_opening_detail,
    make_organization_row,
    make_program,
    make_referral_detail,
    opening_payload,
    promote_to_admin,
    referral_payload,
)

pytestmark = pytest.mark.asyncio


# --- Per-kind row builders -----------------------------------------------


def _referral_post(*, owner_id, description: str = "ref", **overrides) -> Post:
    post = Post(kind="referral", owner_id=owner_id)
    post.referral_detail = make_referral_detail(description=description, **overrides)
    return post


def _opening_post(
    *, owner_id, practice_name: str = "Practice", clinician: Clinician | None = None
) -> Post:
    if clinician is None:
        clinician = make_clinician_with_org(
            owner_id=owner_id, practice_name=practice_name
        )
    if clinician.id is None:
        clinician.id = uuid.uuid4()
    post = Post(kind="clinician_opening", owner_id=owner_id)
    detail = make_opening_detail(clinician_id=clinician.id)
    detail.clinician = clinician
    # Wire the affiliation the opening announces — production posts
    # always carry it (`_resolve_affiliation_context`), and the view
    # reads practice facts (org, location, payment) from here, not
    # through the clinician's primary-affiliation proxies.
    detail.clinician_affiliation = clinician.primary_clinician_affiliation
    post.opening_detail = detail
    return post


def _intake_post(*, owner_id, org_id, program: Program | None = None) -> Post:
    """Build a `kind='program_intake'` Post row with a fresh Program +
    IntakeDetail attached. `org_id` is required because Program FKs to
    Organization and the test session needs the parent row present."""
    if program is None:
        program = make_program(owner_id=owner_id, org_id=org_id)
    if program.id is None:
        program.id = uuid.uuid4()
    post = Post(kind="program_intake", owner_id=owner_id)
    # The intake is self-describing now — its announcement profile
    # (services / age_groups / genders / cost) lives on the detail row,
    # not the linked Program.
    detail = make_intake_detail(
        program_id=program.id,
        services=["therapy_group"],
        age_groups=["adolescents_14_18"],
        genders=[],
        cost=None,
    )
    detail.program = program
    post.intake_detail = detail
    return post


# Each kind paired with its row builder. The URL family is the same
# for every kind (`/posts`) — only the row's stored `kind` value differs.
_KINDS = [
    ("referral", _referral_post),
    ("clinician_opening", _opening_post),
]


# --- Routes mount + 200 smoke --------------------------------------------


async def test_list_route_responds_200(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/posts` responds 200 on an empty database."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200


async def test_search_route_responds_200(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    response = await authenticated_client.get("/posts/search")
    assert response.status_code == 200


async def test_form_new_picker_responds_200(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/posts/form` (no `?kind=`) renders the kind-picker page so the
    user can pick which kind to create. Rendered via the shared
    `_picker.html` macro — one card per kind. Headings come from
    `POST_KINDS[k].noun` (the SOT after #1330); descriptions come from
    `POST_KINDS[k].picker_description`. Tiles for kinds whose
    capability the viewer doesn't hold render as a locked-CTA instead
    of a navigable `?kind=` link. For the default test user (no
    verified email, no claims, no programs):

    - `program_intake` is locked on `capabilities.check_program_intake`
      (REASON_PROGRAM_INTAKE_LOCKED — email + verified org rep + owned
      program).
    - `referral` and `clinician_opening` are locked on
      `capabilities.can_act_as_provider`
      (REASON_NOT_A_VERIFIED_PROVIDER — email + (Claim A OR Claim B)).
    """
    response = await authenticated_client.get("/posts/form")
    assert response.status_code == 200
    body = response.text
    for heading in ("Referral", "Opening", "Program intake"):
        assert heading in body
    # All three tiles are locked for the default test user, so none of
    # them carry a navigable create-form link. Scoped to the picker's
    # `/posts/form?kind=` targets — the global chrome now carries a `/`
    # home brand/breadcrumb link, which is a different URL family and must
    # not trip this check.
    for kind in ("referral", "clinician_opening", "program_intake"):
        assert f"/posts/form?kind={kind}" not in body
    assert 'data-locked-cta="program_intake_locked"' in body
    assert 'data-locked-cta="network_unverified"' in body
    # The picker no longer wraps its heading in a `<header>` band
    # (#1330 — the cards render flatter via Pico's default chrome).
    assert "<header>" not in body


@pytest.mark.parametrize("kind", ["referral", "clinician_opening", "program_intake"])
async def test_form_new_with_kind_responds_200(
    kind: str,
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/posts/form?kind=<value>` renders the kind-specific create form
    (one per registered kind in `POST_KINDS`)."""
    response = await authenticated_client.get(f"/posts/form?kind={kind}")
    assert response.status_code == 200


# --- Search form: kind filter is present ---------------------------------


async def test_search_form_renders_kind_filter(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """The whole-supertype face exposes a `kind` filter on its search
    form so the viewer can narrow the unified feed to one kind. The
    filter is a multi-select with every registered kind as a choice.
    The visible labels come from `POST_KINDS[k].noun` — the same SOT
    the /posts/form picker headings read from (#1330), so the sidebar
    and the picker can't drift."""
    response = await authenticated_client.get("/posts/search")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    kind_inputs = tree.css('form [name="kind"]')
    assert kind_inputs, "/posts/search did not render a `kind` input"
    values = {inp.attributes.get("value") for inp in kind_inputs}
    assert {"referral", "clinician_opening", "program_intake"} <= values
    # Visible labels match the canonical nouns (capital-case). Scope
    # to the `kind` fieldset's <label>s to avoid catching other
    # checkbox labels on the page.
    fieldset = next(
        fs
        for fs in tree.css("fieldset.search-checkbox-fieldset")
        if fs.css_first("legend") and fs.css_first("legend").text(strip=True) == "Type"
    )
    visible = {lbl.text(strip=True) for lbl in fieldset.css("label")}
    assert {"Referral", "Opening", "Program intake"} <= visible


async def test_search_uses_framework_filter_form(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/posts/search` uses the shared `filter_field` macro from
    `_shared/_filter_field.html` — the same macro that renders the inline
    sidebar on `/posts`. Both surfaces are driven by the spec's declared
    Filter objects, so control shapes and labels stay in sync automatically."""
    response = await authenticated_client.get("/posts/search")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # The framework macro uses search-checkbox-fieldset for multi-choice filters.
    sections = tree.css("fieldset.search-checkbox-fieldset")
    assert (
        sections
    ), "/posts/search did not render any search-checkbox-fieldset elements"
    legends = [s.css_first("legend").text(strip=True) for s in sections]
    # Multi-choice filters from the spec: kind(Type), state(State),
    # age_group(Age groups), language(Languages), insurance(Insurance).
    # The `level_of_care` / `modality` axes were removed entirely — no post
    # kind models treatment settings or modalities anymore.
    assert "Type" in legends, f"Expected 'Type' legend in /posts/search: {legends}"
    assert "Age groups" in legends, f"Expected 'Age groups' in /posts/search: {legends}"
    assert "Insurance" in legends, f"Expected 'Insurance' in /posts/search: {legends}"


async def test_list_has_browse_layout_with_filter_sidebar(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/posts` list renders a `.browse-layout` with a `.filter-sidebar` that
    embeds the framework filter form inline. The sidebar uses the same
    `filter_field` macro as `/posts/search` so both surfaces stay in sync.

    Unlike the full-page `/posts/search`, each sidebar filter is wrapped in
    a Pico accordion (`<details class="filter-accordion">`) that starts
    folded; the section heading lives in the `<summary>`, so the macro
    suppresses its own `<legend>` to avoid duplicating the title."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    sidebar = tree.css_first(".filter-sidebar")
    assert sidebar, "/posts did not render a .filter-sidebar element"
    # Each filter is its own folded accordion; the heading is the <summary>.
    accordions = sidebar.css("details.filter-accordion")
    assert accordions, "/posts sidebar did not render any filter accordions"
    assert all(
        "open" not in a.attributes for a in accordions
    ), "Sidebar accordions must start folded (no `open` attribute)"
    summaries = [a.css_first("summary").text(strip=True) for a in accordions]
    assert "Type" in summaries, f"Expected 'Type' accordion in sidebar: {summaries}"
    assert (
        "Insurance" in summaries
    ), f"Expected 'Insurance' accordion in sidebar: {summaries}"
    # The heading moved to <summary>; the inner fieldset no longer repeats it
    # as a <legend>.
    multi_fieldsets = sidebar.css("fieldset.search-checkbox-fieldset")
    assert multi_fieldsets, "/posts sidebar did not render any filter fieldsets"
    assert all(
        fs.css_first("legend") is None for fs in multi_fieldsets
    ), "Sidebar fieldsets should not duplicate the accordion summary as a <legend>"


# --- List filter: ?kind= narrows the feed --------------------------------


async def test_list_kind_filter_narrows_to_one_kind(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """`/posts?kind=referral` narrows the feed to that kind. Without
    a filter the feed includes every kind in the database."""
    author = create_test_user(username=f"a-{uuid.uuid4()}")
    org = Organization(owner_id=author.id, name=f"Org {uuid.uuid4()}")
    org.id = uuid.uuid4()
    org.root_org_id = org.id
    referral = _referral_post(owner_id=author.id)
    opening = _opening_post(owner_id=author.id)
    intake = _intake_post(owner_id=author.id, org_id=org.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(org)
            session.add(referral)
            session.add(opening)
            session.add(intake)

    # No filter → every kind visible.
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    kinds_unfiltered = {
        c.attributes.get("data-kind")
        for c in HTMLParser(response.text).css("#posts-list [data-kind]")
    }
    assert {"referral", "clinician_opening", "program_intake"} <= kinds_unfiltered

    # Filtered to one kind → only that kind.
    response = await authenticated_client.get("/posts?kind=referral")
    assert response.status_code == 200
    kinds_filtered = {
        c.attributes.get("data-kind")
        for c in HTMLParser(response.text).css("#posts-list [data-kind]")
    }
    assert kinds_filtered == {
        "referral"
    }, f"/posts?kind=referral returned: {kinds_filtered!r}"


# --- Browse chrome: no toolbar, no intent toggle, filter summary present -


async def test_list_omits_toolbar_and_intent_toggle(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """The posts browse suppresses the shared list toolbar (no page `<h1>`,
    no "Create post" action — posting is offered by the global "+ Post" nav
    button) and renders no Referrals/Openings intent toggle. The `?kind=`
    facet is reachable via the sidebar filter form instead."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("div.toolbar") is None
    assert tree.css_first('nav[aria-label="Post intent"]') is None


async def test_list_filter_summary_reads_active_filter_count(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """The results column opens with a summary header. Filtering by kind makes
    it read "Showing results with 1 filter." above a small `.meta` row with an
    "Edit" link (to the dedicated search page carrying the live query string),
    a "Clear" link (back to the bare list path), and — for a signed-in viewer —
    a "Save" link that opens the save-search modal (see
    `test_list_filter_summary_offers_save_search_modal`)."""
    response = await authenticated_client.get("/posts?kind=referral")
    assert response.status_code == 200
    summary = HTMLParser(response.text).css_first(".browse-results > header")
    assert summary is not None
    # The count sentence is full-weight text; only the action links carry
    # `.meta` (no button-styled actions menu).
    assert "Showing results with" in summary.text()
    assert "1 filter" in summary.text()
    meta = summary.css_first("p.meta")
    assert meta is not None
    assert summary.css_first("menu.filter-summary-actions") is None
    links = {a.text(strip=True): a.attributes.get("href") or "" for a in meta.css("a")}
    assert set(links) == {"Edit", "Clear", "Save"}
    assert links["Edit"].startswith("/posts/search")
    assert links["Clear"] == "/posts"


async def test_list_filter_summary_offers_save_search_modal(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """With active filters, a signed-in viewer gets a "Save" link in the
    results-summary meta that targets the save-search Pico `<dialog>` (moved
    out of the sidebar into a modal, #1591-follow-up). The dialog carries the
    save form: a hidden `filters` field (the live query, JSON-encoded), the
    `name` input, and the "Save search" submit."""
    response = await authenticated_client.get("/posts?kind=referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    save_link = tree.css_first('.browse-results > header a[data-target="save-search"]')
    assert save_link is not None
    assert save_link.text(strip=True) == "Save"
    dialog = tree.css_first("dialog#save-search")
    assert dialog is not None, "save-search modal must be present"
    assert dialog.css_first('input[type="hidden"][name="filters"]') is not None
    assert dialog.css_first('input[name="name"]') is not None
    submit = dialog.css_first('button[type="submit"]')
    assert submit is not None and submit.text(strip=True) == "Save search"
    # The Pico modal close button (rel=prev) also toggles via data-target.
    assert dialog.css_first('button[rel="prev"][data-target="save-search"]') is not None


async def test_list_filter_summary_hides_save_when_unfiltered(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """With no active filters there's nothing worth saving, so neither the
    "Save" link nor the save-search dialog renders — the summary slot only
    fires in the filtered branch (`active_filter_count`)."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first('a[data-target="save-search"]') is None
    assert tree.css_first("dialog#save-search") is None


# --- List filter: ?owner=me scopes to the viewer's own posts -------------


async def test_list_owner_me_scopes_to_viewer_owned_posts(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """`/posts?owner=me` narrows the feed to posts the viewer owns — the
    foundation of the "My posts" view. Without the filter both owners'
    posts list; with it, only the viewer's. Mirrors the clinician/org
    `?owner=me` radio."""
    author = create_test_user(username=f"a-{uuid.uuid4()}")
    mine = _referral_post(owner_id=logged_in_user.id, description="mine")
    theirs = _referral_post(owner_id=author.id, description="theirs")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(mine)
            session.add(theirs)

    # Feed rows carry no `data-row-id`; each row's headline links to
    # `/posts/{id}`, so resolve which posts rendered by their detail hrefs.
    def _rendered_ids(html: str) -> set[str]:
        return {
            a.attributes.get("href", "").rsplit("/", 1)[-1]
            for a in HTMLParser(html).css(
                "#posts-list .post-feed-row a.post-feed-headline-text"
            )
        }

    # No filter → both owners' posts visible.
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    ids_unfiltered = _rendered_ids(response.text)
    assert {str(mine.id), str(theirs.id)} <= ids_unfiltered

    # `?owner=me` → only the viewer's own post.
    response = await authenticated_client.get("/posts?owner=me")
    assert response.status_code == 200
    ids_filtered = _rendered_ids(response.text)
    assert str(mine.id) in ids_filtered
    assert str(theirs.id) not in ids_filtered


# --- Detail / edit-form route works across kinds -------------------------


@pytest.mark.parametrize("kind,builder", _KINDS)
async def test_detail_route_works_for_each_kind(
    kind: str,
    builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """`/posts/{id}` resolves any registered kind — no kind-lock 404
    on the whole-supertype face."""
    author = create_test_user(username=f"a-{uuid.uuid4()}")
    post = builder(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200


@pytest.mark.parametrize("kind,builder", _KINDS)
async def test_edit_form_route_works_for_each_kind(
    kind: str,
    builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """`/posts/{id}/form` resolves any registered kind and dispatches
    to the kind-specific edit template."""
    author = logged_in_user
    post = builder(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200


# --- Connect panel visibility: hidden on your own post -------------------


@pytest.mark.parametrize("kind,builder", _KINDS)
async def test_connect_panel_hidden_on_own_post(
    kind: str,
    builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The "Connect with the provider" panel is meaningless when the
    viewer IS the provider — it's hidden on a post the viewer owns
    (`is_self`) and shown on someone else's post."""
    mine = builder(owner_id=logged_in_user.id)
    other_owner = create_test_user(username=f"other-{uuid.uuid4()}")
    theirs = builder(owner_id=other_owner.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other_owner)
            session.add(mine)
            session.add(theirs)

    own = await authenticated_client.get(f"/posts/{mine.id}")
    assert own.status_code == 200
    assert HTMLParser(own.text).css_first('[data-row-id="connect-panel"]') is None

    other = await authenticated_client.get(f"/posts/{theirs.id}")
    assert other.status_code == 200
    assert HTMLParser(other.text).css_first('[data-row-id="connect-panel"]') is not None


# --- Referral detail: grouped fact display (mirrors the create/edit form) -
#
# These pin the read-side / write-side parity introduced when the
# referral detail page (`posts/_shared/_referral_facts.html`) adopted the
# form's four-section grouping. The form's sections live in
# `_form_referral.html`; the detail's matching headings live here.


def _verified_provider_clinician(owner_id):
    """A verified, NPI-matched clinician owned by the viewer so they
    clear `can_act_as_provider` — the gate that un-redacts the client
    address on the detail page (see `test_message_send_verified_user...`
    for the same setup on the message route)."""
    clinician = make_clinician_with_org(owner_id=owner_id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    return clinician


async def test_referral_detail_groups_facts_like_the_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A fully-populated referral detail surfaces the same four section
    headings as the create/edit form — Logistics / Service type / About
    the client / Payment options — as `fact_group` headings inside one
    aligned `facts_grid`, with the relevant `data-fact` rows under them."""
    viewer = _verified_provider_clinician(logged_in_user.id)
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(
        owner_id=author.id,
        session_format=["in_person", "virtual"],
        services=["therapy_individual"],
        age_groups=["adults_25_64"],
        pronouns=["she_her"],
        languages=["en"],
        insurance_carriers=["aetna"],
        accepts_private_pay=True,
        sliding_scale=True,
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    headings = [h.text(strip=True) for h in tree.css(".facts-grid > h2.fact-group")]
    assert headings == list(REFERRAL_SECTION_ORDER), headings

    facts = {n.attributes.get("data-fact") for n in tree.css(".facts-grid [data-fact]")}
    assert {
        # Logistics is now one consolidated location row (key `address`),
        # not separate address + in-person/virtual session rows.
        "address",
        "services",
        "age",
        "pronouns",
        "languages",
        # Narrative is a row of "About the client" (mirrors the form's
        # "Narrative" field), not a separate section.
        "narrative",
        # No in-network row — a non-empty carrier list is the in-network
        # statement.
        "insurance_carriers",
        "accepts_private_pay",
        "sliding_scale",
    } <= facts, facts
    assert "accepts_in_network" not in facts, facts
    # The separate session rows folded into the location row.
    assert "in_person_sessions" not in facts, facts
    assert "virtual_sessions" not in facts, facts


async def test_referral_detail_renders_list_facts_one_per_line(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Multi-value rows (services, and any other list) stack one item per
    line on the detail page via `fact_list` — a bullet-less
    `<ul class="fact-values">` of `<li>`s, not a comma-joined string."""
    viewer = _verified_provider_clinician(logged_in_user.id)
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(
        owner_id=author.id,
        services=["therapy_individual", "therapy_group", "medication_management"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    items = tree.css('[data-fact="services"] ul.fact-values > li')
    labels = [li.text(strip=True) for li in items]
    # Priority sort puts medication_management first; the rest follow in
    # vocab order. Three services → three lines.
    assert labels == [
        "Psychiatry / medication management",
        "Therapy — Individual",
        "Therapy — Group",
    ], labels


async def test_referral_detail_meta_omits_modality_chips(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The referral detail's Logistics group carries the modality in its
    consolidated location row ("· Telehealth"), so the `.post-meta` identity
    line no longer repeats it as chips — only the type pill and date live
    there (the referring provider moved to the about-provider section).
    (Opening/intake keep the chips; that's covered by their own kinds, not
    pinned here.)"""
    viewer = _verified_provider_clinician(logged_in_user.id)
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(owner_id=author.id, session_format=["in_person", "virtual"])
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    meta = tree.css_first(".post-meta")
    assert meta is not None, "the .post-meta identity line should render"
    assert "In-person" not in meta.text(), meta.text()
    assert "Virtual" not in meta.text(), meta.text()
    # The modality moved into the consolidated location row (it moved, not
    # vanished): an in-person + virtual referral reads "…· Telehealth".
    location_dd = tree.css_first('[data-fact="address"] dd')
    assert location_dd is not None, response.text
    assert "Telehealth" in location_dd.text(strip=True), location_dd.text(strip=True)


async def test_referral_detail_suppresses_empty_coverage_group(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A group with nothing to show renders no heading. A referral that
    accepts no payment paths and names no carriers drops the whole
    Payment options section — no bare heading over an empty group."""
    viewer = _verified_provider_clinician(logged_in_user.id)
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(
        owner_id=author.id,
        accepts_private_pay=False,
        sliding_scale=False,
        insurance_carriers=[],
        insurance_carriers_other_text=None,
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    headings = [h.text(strip=True) for h in tree.css(".facts-grid > h2.fact-group")]
    assert REFERRAL_SECTIONS.payment not in headings, headings


async def test_referral_detail_locks_client_address_for_non_provider(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A viewer without provider-network access sees the client-address
    row (so they know the detail exists) but the value is redacted to a
    `locked_field` — the real city/state never reaches the wire."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(owner_id=author.id, location_city="Metropolis")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    address_rows = tree.css('[data-fact="address"]')
    assert address_rows, "expected the client-address row to render (locked)"
    assert tree.css('[data-fact="address"] .locked-redacted'), response.text
    assert "Metropolis" not in response.text


async def test_referral_detail_narrative_is_row_of_about_the_client(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The narrative renders as the `narrative` row inside the "About the
    client" group — same section + position as the form's "Narrative"
    field, not a separate leading block."""
    viewer = _verified_provider_clinician(logged_in_user.id)
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(
        owner_id=author.id,
        description="Teen seeking DBT after a recent move.",
        age_groups=["adolescents_14_18"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    # The "About the client" group is the `<dl>` carrying the age row;
    # the narrative is a sibling row in that same `<dl>`.
    about_dl = next(
        (
            dl
            for dl in tree.css(".facts-grid > dl")
            if dl.css_first('[data-fact="age"]')
        ),
        None,
    )
    assert about_dl is not None, "About-the-client group should render"
    narrative = about_dl.css_first('[data-fact="narrative"] dd')
    assert narrative is not None, "narrative should be a row of About the client"
    assert "Teen seeking DBT" in narrative.text()


async def test_referral_detail_shows_referring_provider_in_connect_card(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A referral surfaces its referring clinician in the shared
    "Connect with the provider" card (the `connect-panel` right rail every
    kind uses) — identity only, alongside the message form — and NOT in
    the meta line."""
    viewer = _verified_provider_clinician(logged_in_user.id)
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    referring = make_clinician_with_org(
        owner_id=author.id,
        practice_name="Reyes Group",
        first_name="Dana",
        last_name="Reyes",
    )
    referring.id = referring.id or uuid.uuid4()
    post = _referral_post(owner_id=author.id)
    post.referral_detail.referring_clinician = referring
    post.referral_detail.clinician_affiliation = referring.primary_clinician_affiliation
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer)
            session.add(author)
            session.add(referring)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    # The referring provider moved OUT of the meta line.
    meta = tree.css_first(".post-meta")
    assert meta is not None, ".post-meta identity line should render"
    assert "Referred by" not in meta.text(), meta.text()

    # ...and INTO the "Connect with the provider" card, where the provider
    # row links the referring clinician.
    panel = tree.css_first('article[data-row-id="connect-panel"]')
    assert panel is not None, "referral should render the connect-with-provider card"
    assert "Connect with the provider" in panel.text()
    provider_dd = panel.css_first('div[data-fact="provider"] dd')
    assert provider_dd is not None, "provider identity row should render"
    assert (
        provider_dd.css_first(f'a[href="/clinicians/{referring.id}"]') is not None
    ), "referring clinician name should link to the clinician detail page"
    # Identity only: a referral suppresses the practice-marketing rows.
    assert panel.css_first('div[data-fact="address"]') is None
    assert panel.css_first('div[data-fact="insurance"]') is None
    # The card also holds the message form (viewer is a verified provider).
    assert panel.css_first("#post-message") is not None


# --- Owner authz invariants ----------------------------------------------


@pytest.mark.parametrize("kind,builder", _KINDS)
async def test_non_owner_cannot_patch(
    kind: str,
    builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A logged-in user who isn't the post owner (and isn't an admin)
    can't PATCH it — `auth_policy=OWNER_OR_ADMIN` is enforced on the
    unified face."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = builder(owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={"description": "hacked", "kind": kind},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("kind,builder", _KINDS)
async def test_admin_can_patch_anyone(
    kind: str,
    builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Admins keep the cross-owner write hatch — `OWNER_OR_ADMIN`'s
    "or admin" branch survives the consolidation."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = builder(owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={"description": "admin-patched", "kind": kind},
    )
    # PATCH bodies vary per kind; we don't pin success here — the
    # important assertion is "not 403". A 400 / 422 on body shape is
    # acceptable; a 403 would be the regression we want to catch.
    assert response.status_code != 403


# --- Form-error re-render (form_error_render opt-in) ---------------------


async def test_clinician_opening_create_form_error_render_is_wired(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Integration smoke for `POST_ENTITY.form_error_render` exercised
    against the clinician_opening kind. HX-Request POST with an invalid
    `clinician_affiliation_id` (a non-UUID string) returns 422 + HTML
    and the response surfaces the failing field's inline error.

    Structural contracts live in their owning layers, not here:

      - HX-Request vs not, 422 vs JSON, `form_errors` dict shape,
        kind-prefix stripping → `src/framework/dispatch/mounts/test_create.py`.
      - Pico-canonical `aria-invalid` + helper-slot rendering →
        `src/framework/templates/_shared/test_form_fields.py`.
    """
    clinician = make_clinician_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    payload = opening_payload(clinician_id=str(clinician.id))
    # Force a 422 on the required affiliation FK by sending a non-UUID
    # value — the only required wire field on the thin opening shape
    # (#1358 PR-f sub-3).
    payload["clinician_affiliation_id"] = "not-a-uuid"

    response = await authenticated_client.post(
        "/posts",
        data=payload,
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert 'name="clinician_affiliation_id"' in response.text
    aff_start = response.text.index('name="clinician_affiliation_id"')
    aff_block = response.text[max(0, aff_start - 200) : aff_start + 200]
    assert 'aria-invalid="true"' in aff_block, aff_block
    # Fragment-only response: the re-render returns just the `<form>`,
    # not the full `new_clinician_opening.html` page (which extends
    # base.html).
    assert "<!DOCTYPE" not in response.text
    assert "<html" not in response.text
    assert "Bedlam Connect" not in response.text


async def test_referral_create_form_error_render_is_wired(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """Integration smoke for `POST_ENTITY.form_error_render` exercised
    against the referral kind — same shape as the clinician_opening
    smoke above, confirms the declarative pattern generalizes across
    kinds. The referral form's `_form_referral.html` imports
    `_shared/form_fields.html` macros `with context`, so the per-field
    `error=`/`current=` are auto-resolved from `form_errors`/`form_values`
    without any template-side threading.
    """
    payload = referral_payload(age_groups=[])

    response = await authenticated_client.post(
        "/posts",
        data=payload,
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("text/html")
    # `multi_select_field` renders a `<div role="group" id="age_groups">`
    # wrapper; the aria-invalid lives on the group, not on each checkbox.
    assert 'id="age_groups"' in response.text
    group_start = response.text.index('id="age_groups"')
    age_block = response.text[max(0, group_start - 200) : group_start + 200]
    assert 'aria-invalid="true"' in age_block, age_block
    # The form re-render now carries a form-level summary banner at the
    # top (via the `form_with_errors` wrapper + `mount_create`'s 422
    # path), so a failed submit is announced near the top of the form
    # instead of only on fields scrolled off-screen above the button.
    assert 'class="form-banner" role="alert"' in response.text
    assert "Please fix the highlighted fields" in response.text
    assert "<!DOCTYPE" not in response.text
    assert "<html" not in response.text
    assert "Bedlam Connect" not in response.text


# --- Clinician-profile gate on create forms ------------------------------


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
async def test_create_form_gate_shown_when_no_clinician_profile(
    kind: str,
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """GET /posts/form?kind=<kind> shows the provider-entity gate when the
    requesting user has no clinician profiles, not the create form. The gate
    copy (`posts/_shared/_require_clinician_profile.html`) nudges toward a
    clinician *or* org."""
    response = await authenticated_client.get(f"/posts/form?kind={kind}")
    assert response.status_code == 200
    assert "Add a clinician or organization first." in response.text
    assert "/clinicians/form" in response.text
    assert "/organizations/form" in response.text
    # The post-create form fields should not be rendered.
    assert 'name="kind"' not in response.text


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
async def test_create_form_shown_when_clinician_profile_exists(
    kind: str,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """GET /posts/form?kind=<kind> renders the create form once the user has
    at least one clinician profile."""
    clinician = make_clinician_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get(f"/posts/form?kind={kind}")
    assert response.status_code == 200
    assert 'name="kind"' in response.text
    assert "Add a clinician or organization first." not in response.text


# Both clinician-authored kinds now expose a single practice picker named
# `clinician_affiliation_id` (one option per affiliation); the server
# derives the clinician FK from the chosen affiliation.
_CLINICIAN_FIELD = {
    "referral": "clinician_affiliation_id",
    "clinician_opening": "clinician_affiliation_id",
}


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
async def test_create_form_preselects_first_clinician(
    kind: str,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The practice picker on new-post forms defaults to the user's first
    affiliation — no placeholder '-- ' option is rendered."""
    clinician = make_clinician_with_org(
        owner_id=logged_in_user.id, practice_name="First Practice"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
    affiliation_id = clinician.clinician_affiliations[0].id

    response = await authenticated_client.get(f"/posts/form?kind={kind}")
    assert response.status_code == 200

    tree = HTMLParser(response.text)
    field_name = _CLINICIAN_FIELD[kind]
    select = tree.css_first(f'select[name="{field_name}"]')
    assert select is not None, f"no <select name={field_name!r}> in response"

    options = select.css("option")
    assert options, "practice select rendered no options"

    # No disabled placeholder.
    assert not any(
        o.attributes.get("disabled") is not None and "--" in (o.text() or "")
        for o in options
    ), "placeholder '--' option should not be present on new form"

    # First (and only) option is pre-selected.
    # selectolax stores boolean HTML attributes (e.g. `selected`) as None, so
    # key presence — not a non-None value — is the correct sentinel.
    assert (
        "selected" in options[0].attributes
    ), "first affiliation option should carry the 'selected' attribute"
    assert str(affiliation_id) in (
        options[0].attributes.get("value") or ""
    ), "selected option value should be the first affiliation's id"


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
async def test_create_form_picker_labels_person_first_with_org(
    kind: str,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The practice picker labels each affiliation **person first, org as
    disambiguator** — `"<First Last> · <Org Name>"` when the affiliation
    points at an organization. The label was just `<Org Name>` before
    #1308 — that erased the person entirely when one user owned multiple
    clinicians, and broke entirely once solo clinicians (whose
    affiliation has `org_id` NULL) became a first-class state."""
    clinician = make_clinician_with_org(
        owner_id=logged_in_user.id,
        practice_name="Brooklyn Therapy",
        first_name="Jane",
        last_name="Smith",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
    affiliation_id = clinician.clinician_affiliations[0].id

    response = await authenticated_client.get(f"/posts/form?kind={kind}")
    assert response.status_code == 200

    tree = HTMLParser(response.text)
    select = tree.css_first(f'select[name="{_CLINICIAN_FIELD[kind]}"]')
    assert select is not None
    option = next(
        o
        for o in select.css("option")
        if o.attributes.get("value") == str(affiliation_id)
    )
    assert option.text(strip=True) == "Jane Smith · Brooklyn Therapy"


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
async def test_create_form_picker_labels_solo_with_name_only(
    kind: str,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Solo clinician: the affiliation row has `org_id` NULL — the label
    is just the clinician's name (no `" · …"` suffix), because there is
    no organizational entity to disclose."""
    from src.domain.models import ClinicianAffiliation

    clinician = make_clinician(
        owner_id=logged_in_user.id,
        first_name="Janet",
        last_name="Solo",
    )
    # Force a stub affiliation with no org — mirrors the PR 2 stub shape.
    clinician.clinician_affiliations = [ClinicianAffiliation(clinician=clinician)]
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
    affiliation_id = clinician.clinician_affiliations[0].id

    response = await authenticated_client.get(f"/posts/form?kind={kind}")
    assert response.status_code == 200

    tree = HTMLParser(response.text)
    select = tree.css_first(f'select[name="{_CLINICIAN_FIELD[kind]}"]')
    assert select is not None
    option = next(
        o
        for o in select.css("option")
        if o.attributes.get("value") == str(affiliation_id)
    )
    assert option.text(strip=True) == "Janet Solo"


# --- Referral form: section labels --------------------------------------


async def test_referral_form_uses_client_oriented_section_labels(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The referral form's structured fields describe the CLIENT (the
    person being placed), not the referrer — so the section legends and
    labels say so. Pins the client-oriented copy introduced when the
    referral/opening data-home split was surfaced in the UI: the payment
    section names the client's payment options. (Languages is the one
    provider-oriented axis — the language the provider should speak — and
    lives under "Service type", pinned separately below.)"""
    clinician = make_clinician_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/posts/form?kind=referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # Parse to text so HTML-escaped apostrophes (`&#39;`) decode.
    page_text = tree.body.text()
    # The reworked referral form groups fields around the referring
    # clinician's mental flow: Logistics / Service type / About the
    # client / Payment options. The original "Client's coverage" /
    # "Provider sought" framing collapsed into these four sections.
    for title in REFERRAL_SECTION_ORDER:
        assert title in page_text, title
    # Payment options carries the insurance-carrier multi-select (the
    # in-network statement — there's no separate "has insurance" checkbox);
    # the payment-path checkboxes lead the section, then the carriers.
    assert (
        tree.css_first('input[name="insurance_carriers"]') is not None
    ), "the Payment options section must carry the insurance_carriers field"


async def test_referral_form_section_titles_come_from_the_shared_source(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The write view's section headings are exactly `REFERRAL_SECTION_ORDER`,
    in order. Paired with `test_referral_detail_groups_facts_like_the_form`
    (which asserts the *read* view's headings against the same tuple), this
    pins that both render from `domain.logic.posts.sections` — a section
    rename is one edit there and can't drift between form and detail."""
    clinician = make_clinician_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/posts/form?kind=referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    titles = [
        h.text(strip=True)
        for h in tree.css(
            "section.form-section > h2, section.form-section > hgroup > h2"
        )
    ]
    assert titles == list(REFERRAL_SECTION_ORDER), titles


async def test_referral_form_languages_is_provider_oriented_under_service_type(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Languages on a referral is a service-fit axis — the language the
    provider must speak (a client seeks a provider who speaks X) — not a
    client demographic. So it lives under the "Service type" section (with
    Services), not "About the client". The label stays terse ("Languages",
    matching the detail page) and the help carries the provider-orientation
    so it isn't read as a client attribute."""
    clinician = make_clinician_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/posts/form?kind=referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    page_text = tree.body.text()
    lang_help = tree.css_first("small#languages-helper")
    assert lang_help is not None, "languages must carry a provider-orientation help"
    assert lang_help.text().strip() == "The language(s) the provider should speak."
    assert "Languages the client speaks" not in page_text
    sections = {
        s.css_first("h2").text(strip=True): s
        for s in tree.css("section.form-section")
        if s.css_first("h2")
    }
    assert REFERRAL_SECTIONS.service_type in sections
    assert (
        sections[REFERRAL_SECTIONS.service_type].css_first('[name="languages"]')
        is not None
    ), "languages must render inside the Service type section"
    about = sections.get(REFERRAL_SECTIONS.about_client)
    assert (
        about is None or about.css_first('[name="languages"]') is None
    ), "languages must no longer live under About the client"


async def test_referral_detail_languages_row_is_under_service_type(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The detail mirrors the form: the languages row renders inside the
    "Service type" fact-group, not "About the client"."""
    viewer = _verified_provider_clinician(logged_in_user.id)
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(
        owner_id=author.id,
        services=["therapy_individual"],
        languages=["es"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # Walk the grid in document order, tracking the current fact-group, to
    # find which group owns the languages row.
    current = None
    owner = None
    for node in tree.css(".facts-grid > *"):
        classes = node.attributes.get("class") or ""
        if node.tag == "h2" and "fact-group" in classes:
            current = node.text(strip=True)
        elif node.css_first('[data-fact="languages"]') is not None:
            owner = current
            break
    assert owner == REFERRAL_SECTIONS.service_type, owner


async def test_referral_form_fields_carry_help_descriptions(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Structured referral fields carry an optional description (the
    `help=` slot on the field macro) so the form guides the referrer on
    what a field is for. Pins the Narrative guidance end-to-end: the
    `<small id="description-helper">` renders inside the field and the
    control is wired to it via `aria-describedby` (Pico's canonical helper
    pattern — the same wiring `_shared/form_fields.html` emits for every
    `help=`)."""
    clinician = make_clinician_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/posts/form?kind=referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    helper = tree.css_first("small#description-helper")
    assert helper is not None, "Narrative field must render a help description"
    assert helper.text().strip().startswith("Briefly describe the patient")
    textarea = tree.css_first('textarea[name="description"]')
    assert textarea is not None
    assert (
        textarea.attributes.get("aria-describedby") == "description-helper"
    ), "the Narrative field must link its help text via aria-describedby"


async def test_referral_form_sections_state_their_perspective(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Each section carries a one-line perspective intro
    (`form_section(description=…)`) so the form makes explicit which
    fields describe the client vs. the provider the client is seeking.
    Pins that the intros render as the muted `<p>` of each section's
    Pico `<hgroup>`."""
    clinician = make_clinician_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/posts/form?kind=referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    descs = {d.text(strip=True) for d in tree.css("section.form-section > hgroup > p")}
    assert {
        "What the client needs a provider to offer.",
        "Payment paths the provider must accept.",
        "Who the client is.",
    } <= descs, descs


async def test_referral_form_age_group_options_are_singular(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A referral describes ONE client, so the age-group `<select>` names
    a single person: its options are the vocabulary's singular labels
    ("Child (0–5)"), not the plural listing form used by the multi-valued
    program/affiliation/search vocabularies. Pins the singular-label wiring
    in `_form_referral.html` against the vocabulary as the source of truth."""
    clinician = make_clinician_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/posts/form?kind=referral")
    assert response.status_code == 200
    select = HTMLParser(response.text).css_first('select[name="age_groups"]')
    assert select is not None, "referral form must render an age_groups <select>"
    # Real options carry a value; the leading placeholder (`value=""`) doesn't.
    option_texts = {
        opt.text().strip()
        for opt in select.css("option")
        if opt.attributes.get("value")
    }
    assert option_texts == set(CLIENT_AGE_GROUP_LABELS_SINGULAR.values())


async def test_opening_create_form_omits_practice_profile_preview(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The opening create form no longer renders the read-only practice-
    profile preview (removed). The picker still selects the practice, and
    the announcement's own self-describing sections (services / delivery /
    clients-served / cost) remain the form body."""
    clinician = make_clinician_with_org(
        owner_id=logged_in_user.id, practice_name="Acme Health"
    )
    clinician.id = clinician.id or uuid.uuid4()
    aff = clinician.primary_clinician_affiliation
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/posts/form?kind=clinician_opening")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    # Preview is gone: no container, no per-affiliation preview cards.
    assert (
        tree.css_first('[data-profile-preview="clinician_affiliation_id"]') is None
    ), "practice-profile preview should be removed from the opening form"
    assert tree.css_first(f'div[data-preview-for="{aff.id}"]') is None

    # The opening is self-describing: the form carries its own
    # service-type / delivery / clients-served / cost sections, on the
    # same vocabularies the referral request side uses.
    page_text = tree.body.text()
    for legend in ("Service type", "Delivery", "Clients served", "Cost"):
        assert legend in page_text, f"opening form missing {legend!r} section/field"
    for field_name in ("services", "session_format", "age_groups", "genders", "cost"):
        assert (
            tree.css_first(f'[name="{field_name}"]') is not None
        ), f"opening form must render a {field_name!r} input"


async def test_intake_create_form_omits_program_profile_preview(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The intake create form no longer renders the read-only program-
    profile preview (removed). The picker still selects the program, and
    the announcement's own self-describing sections (services /
    clients-served / cost) remain the form body. Requires a verified org
    rep who owns a program (the `check_program_intake` gate)."""
    org = make_organization_row(owner_id=logged_in_user.id, name="Acme Health")
    rep = OrgRepresentation(
        user_id=logged_in_user.id,
        org_id=org.id,
        role="coordinator",
        authority_method="admin_review",
        authority_status="verified",
    )
    program = make_program(
        owner_id=logged_in_user.id,
        org_id=org.id,
        website="https://riseiop.example.com",
    )
    program.organization = org
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
            session.add(rep)
            session.add(program)

    response = await authenticated_client.get("/posts/form?kind=program_intake")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    # Preview is gone: no container, no per-program preview cards.
    assert (
        tree.css_first('[data-profile-preview="program_id"]') is None
    ), "program-profile preview should be removed from the intake form"
    assert tree.css_first(f'div[data-preview-for="{program.id}"]') is None

    # The intake is self-describing now: the form carries its own
    # service-type / clients-served / cost sections, on the same
    # vocabularies the referral request side uses. (A Program is a single
    # group offering, so there is no `session_format` / delivery section.)
    page_text = tree.body.text()
    for legend in ("Service type", "Clients served"):
        assert legend in page_text, f"intake form missing {legend!r} section"
    for field_name in ("services", "age_groups", "genders", "cost"):
        assert (
            tree.css_first(f'[name="{field_name}"]') is not None
        ), f"intake form must render a {field_name!r} input"


# --- Anonymization gate (can_act_as_provider) ---------------------------------


async def test_list_has_no_inline_verify_notice_for_unverified(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """The /posts list carries no inline verify notice, even for an
    unverified viewer. Poster names / contact are anonymized server-side;
    the verify-to-post step on the `/users/me` card is where verification
    is explained — the old `posts-verify-notice` is gone."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    assert "posts-verify-notice" not in response.text
    # No inline locked placeholder in the list body — locked affordances only
    # appear in the toolbar (locked_action for Create) and globally in the
    # locked-cta popovers rendered by base.html.
    tree = HTMLParser(response.text)
    main = tree.css_first("main")
    assert main is not None
    assert main.css_first("button.locked-ghost-btn") is None


# NOTE: the posts browse no longer renders a toolbar Create CTA (the page
# suppresses the shared list toolbar entirely — see
# `test_list_omits_toolbar_and_intent_toggle`). Posting is offered by the
# always-present global "+ Post" nav button, pinned in the page-header / nav
# tests; the server-side post gate (claim required) is exercised by the
# create/patch authz tests above. There is therefore no per-claim toolbar-CTA
# visibility to assert here.


async def test_detail_hides_message_form_and_shows_cta_for_unverified(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Unverified users see a locked Message CTA (no form, no contact
    info) on post detail — the inline form is not rendered, and the
    poster's email address is not sent to the browser. Replaces the
    prior `mailto:`-button assertion: the same `can_act_as_provider`
    gate now hides the form instead of disabling a button."""
    author = create_test_user(
        username=f"detail-author-{uuid.uuid4()}",
        email=f"detail-author-{uuid.uuid4()}@example.com",
    )
    post = _referral_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    assert author.email not in response.text
    tree = HTMLParser(response.text)
    assert tree.css_first(f"form[hx-post='/posts/{post.id}/message']") is None
    assert "Message" in response.text


async def test_detail_shows_message_form_for_verified(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Verified users (Claim A active) see the inline message form on
    the post detail page — POSTs to `/posts/{id}/message`, which
    dispatches the transactional email server-side. The poster's raw
    email address is never sent to the browser; the form route
    resolves the recipient from the post row."""
    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    author_email = f"detail-author-{uuid.uuid4()}@example.com"
    author = create_test_user(
        username=f"detail-author-{uuid.uuid4()}",
        email=author_email,
    )
    post = _referral_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    assert author_email not in response.text
    tree = HTMLParser(response.text)
    form = tree.css_first(f"form[hx-post='/posts/{post.id}/message']")
    assert form is not None
    assert form.css_first("textarea[name='body']") is not None


async def test_detail_redacts_identity_rows_as_locked_placeholders_for_unverified(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A viewer who can't read the full feed sees the provider identity
    and address rows on post detail as `locked_field` / `locked_name`
    placeholders (lock icon + fix link), not silently dropped. The real
    links + address value are NOT emitted — withholding, not CSS-hiding."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    clinician = make_clinician_with_org(owner_id=author.id, practice_name="Acme Health")
    clinician.id = clinician.id or uuid.uuid4()
    post = _opening_post(owner_id=author.id, clinician=clinician)
    org_id = clinician.org.id
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    # The rows still render (the viewer knows the detail exists). The
    # provider row carries the withheld clinician + org behind
    # `locked_name`; the address carries a `locked_field`.
    for fact_key in ("provider", "address"):
        dd = tree.css_first(f'div[data-fact="{fact_key}"] dd')
        assert dd is not None, f"{fact_key} row should still render when redacted"
        assert (
            dd.css_first("button.locked-ghost-btn") is not None
        ), f"{fact_key} should render a locked placeholder"

    # ...but the real navigable links + the address value are withheld.
    assert tree.css_first(f"a[href='/clinicians/{clinician.id}']") is None
    assert tree.css_first(f"a[href='/organizations/{org_id}']") is None
    assert "Springfield, IL" not in response.text


async def test_detail_shows_identity_rows_for_verified_viewer(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A verified viewer (can read the full feed) sees the real practice /
    organization links (in the Connect panel) and the un-redacted location
    (in the body's Logistics row) — no locked placeholders."""
    viewer_clinician = make_clinician_with_org(
        owner_id=logged_in_user.id, npi="1234567890"
    )
    viewer_clinician.npi_match_status = "matched"
    viewer_clinician.clinician_verified = True

    author = create_test_user(username=f"author-{uuid.uuid4()}")
    clinician = make_clinician_with_org(owner_id=author.id, practice_name="Acme Health")
    clinician.id = clinician.id or uuid.uuid4()
    post = _opening_post(owner_id=author.id, clinician=clinician)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer_clinician)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    assert tree.css_first(f"a[href='/clinicians/{clinician.id}']") is not None
    # Location renders un-redacted in the body's Logistics row (a
    # `location_summary` — state always present, city only when in-person).
    address_dd = tree.css_first('[data-fact="address"] dd')
    assert address_dd is not None, "Logistics location row should render"
    assert "IL" in address_dd.text(), address_dd.text()
    assert tree.css_first("button.locked-ghost-btn") is None


async def test_opening_detail_renders_practice_context_in_body_not_panel(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Opening detail renders the post's own self-describing profile
    (services / cohort / cost / schedule) AND the steady-state practice
    *context* (insurance posture + how-to-refer website) in the body — the
    providing-side mirror of the referral. The `connect-panel` is
    identity-only: the provider links + the message form, no practice
    context."""
    # A verified viewer so the provider identity links render un-redacted.
    viewer_clinician = make_clinician_with_org(
        owner_id=logged_in_user.id, npi="1234567890"
    )
    viewer_clinician.npi_match_status = "matched"
    viewer_clinician.clinician_verified = True
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    clinician = make_clinician_with_org(owner_id=author.id, practice_name="Acme Health")
    clinician.id = clinician.id or uuid.uuid4()
    aff = clinician.primary_clinician_affiliation
    aff.sliding_scale = True
    aff.website = "https://acme.example.com"
    post = _opening_post(owner_id=author.id, clinician=clinician)
    post.opening_detail.schedule_text = "Mornings only"
    post.opening_detail.services = ["therapy_individual"]
    post.opening_detail.age_groups = ["adults_25_64"]
    post.opening_detail.cost = "$150/session"
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer_clinician)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    panel = tree.css_first('article[data-row-id="connect-panel"]')
    assert panel is not None, "connect-with-provider card should render"
    assert "Connect with the provider" in panel.text()
    # The provider identity row carries the clinician (linked) followed
    # by the org (linked) — the shared `provider_ref` denotation.
    provider_dd = panel.css_first('div[data-fact="provider"] dd')
    assert provider_dd is not None, "provider identity row should render"
    assert (
        provider_dd.css_first(f"a[href='/clinicians/{clinician.id}']") is not None
    ), "clinician name should link to the clinician detail page"
    assert (
        provider_dd.css_first(f"a[href='/organizations/{clinician.org.id}']")
        is not None
    ), "org name should link to the organization detail page"
    # The panel is identity-only — the practice context is NOT in it.
    assert panel.css_first('div[data-fact="insurance"]') is None
    assert panel.css_first('div[data-fact="website"]') is None
    # Insurance posture + how-to-refer website render in the body's Coverage
    # section (the providing-side mirror of the referral's Coverage).
    main = tree.css_first("div.post-detail-main")
    assert main is not None
    assert "Coverage" in main.text()
    for fact_key in ("insurance", "website"):
        assert (
            main.css_first(f'div[data-fact="{fact_key}"]') is not None
        ), f"{fact_key} should render in the opening body"
    assert "Sliding scale" in main.text()
    # The opening's own self-describing profile renders in the body too.
    for fact_key in ("services", "ages", "cost", "schedule_notes"):
        assert (
            main.css_first(f'div[data-fact="{fact_key}"]') is not None
        ), f"{fact_key} should render in the opening body"
    assert "Therapy — Individual" in tree.text()


async def test_intake_detail_renders_program_context_in_body_not_panel(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Intake detail renders the program's how-to-refer context (website /
    referral_instructions) in the body's "How to refer" section via
    `program_facts`. The `connect-panel` is identity-only: the provider
    links + the message form. The intake's self-describing profile
    (services / age groups) renders in the body too."""
    # A verified viewer so the provider identity links render un-redacted.
    viewer_clinician = make_clinician_with_org(
        owner_id=logged_in_user.id, npi="1234567890"
    )
    viewer_clinician.npi_match_status = "matched"
    viewer_clinician.clinician_verified = True
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    org = make_organization_row(owner_id=author.id, name="Acme Health")
    program = make_program(
        owner_id=author.id,
        org_id=org.id,
        website="https://riseiop.example.com",
    )
    program.organization = org
    post = _intake_post(owner_id=author.id, org_id=org.id, program=program)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer_clinician)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    panel = tree.css_first('article[data-row-id="connect-panel"]')
    assert panel is not None, "program connect-with-provider card should render"
    assert "Connect with the provider" in panel.text()
    provider_dd = panel.css_first('div[data-fact="provider"] dd')
    assert provider_dd is not None, "provider identity row should render"
    assert (
        provider_dd.css_first(f"a[href='/programs/{program.id}']") is not None
    ), "program name should link to the program detail page"
    assert (
        provider_dd.css_first(f"a[href='/organizations/{org.id}']") is not None
    ), "org name should link to the organization detail page"
    # The panel is identity-only — the how-to-refer context is NOT in it.
    assert panel.css_first('div[data-fact="website"]') is None
    # Website renders in the body's "How to refer" section.
    main = tree.css_first("div.post-detail-main")
    assert main is not None
    assert "How to refer" in main.text()
    assert (
        main.css_first('div[data-fact="website"]') is not None
    ), "website should render in the intake body"
    assert "https://riseiop.example.com" in main.text()
    # The intake's own self-describing profile (services / cohort) renders
    # in the body too. `_intake_post` seeds services=["therapy_group"],
    # age_groups=[adolescents].
    for fact_key in ("services", "ages"):
        assert (
            main.css_first(f'div[data-fact="{fact_key}"]') is not None
        ), f"{fact_key} should render in the intake body"
    assert "Therapy — Group" in tree.text()


# --- POST /posts/{id}/message (in-app contact form) --------------------------


async def test_message_send_unverified_user_is_forbidden(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
    monkeypatch,
):
    """A claimless viewer can't see the form (existing visibility gate),
    so the route must also reject the request server-side. Mirrors the
    `can_act_as_provider` gate that hid the prior `mailto:` button."""
    send_mock = pytest.importorskip("unittest.mock").AsyncMock()
    monkeypatch.setattr(
        "src.domain.logic.posts.handlers.send_post_message_email", send_mock
    )

    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.post(
        f"/posts/{post.id}/message", json={"body": "hello"}
    )
    assert response.status_code == 403
    assert send_mock.call_count == 0


async def test_message_send_verified_user_dispatches_email(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
    monkeypatch,
):
    """Verified-network viewer (`can_act_as_provider=True`) reaches the
    handler and we hand the post + sender + body to the domain email
    wrapper. Tests for `Reply-To`, recipient, and link shape live in
    `src/domain/logic/posts/test_emails.py` — this test only pins the
    handoff."""
    from unittest.mock import AsyncMock

    send_mock = AsyncMock()
    monkeypatch.setattr(
        "src.domain.logic.posts.handlers.send_post_message_email", send_mock
    )

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
            session.add(author)
            session.add(post)

    response = await authenticated_client.post(
        f"/posts/{post.id}/message",
        json={"body": "I have a referral that matches"},
    )
    assert response.status_code == 200
    assert "Message sent" in response.text
    assert send_mock.call_count == 1
    kwargs = send_mock.call_args.kwargs
    assert kwargs["post"].id == post.id
    assert kwargs["sender"].id == logged_in_user.id
    assert kwargs["body"] == "I have a referral that matches"


async def test_message_send_404_when_post_missing(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
    monkeypatch,
):
    """Unknown post id returns 404 — even for an authorized sender.
    The `can_act_as_provider` check fires first, so the user must clear
    that gate before the missing-post path is reachable."""
    from unittest.mock import AsyncMock

    send_mock = AsyncMock()
    monkeypatch.setattr(
        "src.domain.logic.posts.handlers.send_post_message_email", send_mock
    )

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.post(
        f"/posts/{uuid.uuid4()}/message", json={"body": "hi"}
    )
    assert response.status_code == 404
    assert send_mock.call_count == 0


async def test_message_send_rejects_blank_body(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
    monkeypatch,
):
    """Empty / whitespace-only bodies are 422 — no point shipping a
    blank email."""
    from unittest.mock import AsyncMock

    send_mock = AsyncMock()
    monkeypatch.setattr(
        "src.domain.logic.posts.handlers.send_post_message_email", send_mock
    )

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
            session.add(author)
            session.add(post)

    response = await authenticated_client.post(
        f"/posts/{post.id}/message", json={"body": "   "}
    )
    assert response.status_code == 422
    assert send_mock.call_count == 0


# --- Post connections (#775) -------------------------------------------------


def _verified_sender_clinician(owner_id) -> Clinician:
    clinician = make_clinician_with_org(owner_id=owner_id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    return clinician


async def test_message_send_own_post_is_forbidden(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
    monkeypatch,
):
    """The panel is hidden on your own post, but a crafted request must
    also be refused server-side — an author can't connect to themself."""
    from unittest.mock import AsyncMock

    send_mock = AsyncMock()
    monkeypatch.setattr(
        "src.domain.logic.posts.handlers.send_post_message_email", send_mock
    )
    post = _referral_post(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(_verified_sender_clinician(logged_in_user.id))
            session.add(post)

    response = await authenticated_client.post(
        f"/posts/{post.id}/message", json={"body": "hi me"}
    )
    assert response.status_code == 403
    assert send_mock.call_count == 0


async def test_message_send_announces_connection_only_the_first_time(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
    monkeypatch,
):
    """The first message flips the sender to Connected; a repeat send
    doesn't re-announce it (the panel already shows the Connected line
    above the form for an existing edge)."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "src.domain.logic.posts.handlers.send_post_message_email", AsyncMock()
    )
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(_verified_sender_clinician(logged_in_user.id))
            session.add(author)
            session.add(post)

    first = await authenticated_client.post(
        f"/posts/{post.id}/message", json={"body": "hello"}
    )
    assert first.status_code == 200
    assert HTMLParser(first.text).css_first("[data-row-id='connected']") is not None

    second = await authenticated_client.post(
        f"/posts/{post.id}/message", json={"body": "hello again"}
    )
    assert second.status_code == 200
    assert "Message sent" in second.text
    assert HTMLParser(second.text).css_first("[data-row-id='connected']") is None


async def test_detail_shows_connected_state_only_when_connected(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
    monkeypatch,
):
    """The relationship, not the click, is the source of truth: after a
    message, every later view of the post shows Connected, and the form
    stays so the sender can write again."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "src.domain.logic.posts.handlers.send_post_message_email", AsyncMock()
    )
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(_verified_sender_clinician(logged_in_user.id))
            session.add(author)
            session.add(post)

    before = HTMLParser((await authenticated_client.get(f"/posts/{post.id}")).text)
    assert before.css_first("[data-row-id='connected']") is None

    await authenticated_client.post(f"/posts/{post.id}/message", json={"body": "hi"})

    after = HTMLParser((await authenticated_client.get(f"/posts/{post.id}")).text)
    panel = after.css_first("article[data-row-id='connect-panel']")
    connected = panel.css_first("[data-row-id='connected']")
    assert connected is not None
    assert connected.text().startswith("Connected · ")
    assert panel.css_first(f"form[hx-post='/posts/{post.id}/message']") is not None


# --- Edit-form picker: options come from the post's owner -----------------


def _post_on_affiliation(kind: str, *, owner_id, clinician: Clinician) -> Post:
    """A `kind` post whose practice picker points at ``clinician``'s
    first affiliation."""
    aff = clinician.clinician_affiliations[0]
    post = Post(kind=kind, owner_id=owner_id)
    if kind == "referral":
        detail = make_referral_detail()
        detail.referring_clinician = clinician
    else:
        detail = make_opening_detail(clinician_id=clinician.id)
        detail.clinician = clinician
    detail.clinician_affiliation = aff
    setattr(post, f"{'referral' if kind == 'referral' else 'opening'}_detail", detail)
    return post


def _picker_values(html: str, field: str) -> set[str]:
    select = HTMLParser(html).css_first(f'select[name="{field}"]')
    assert select is not None
    return {o.attributes.get("value") for o in select.css("option")}


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
async def test_admin_edit_form_lists_owner_practices_not_admins(
    kind: str,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A superuser editing someone else's post sees the *owner's*
    practices in the picker — never their own. Before the fix the
    picker iterated `current_user.clinicians`, so an admin with no
    clinicians saw an empty dropdown and one with clinicians was
    offered their own practices (re-pointing the post on save)."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    admin_clinician = make_clinician_with_org(
        owner_id=logged_in_user.id, practice_name="Admin Practice"
    )
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    owner_clinician = make_clinician_with_org(
        owner_id=owner.id, practice_name="Owner Practice"
    )
    owner_clinician.id = uuid.uuid4()
    post = _post_on_affiliation(kind, owner_id=owner.id, clinician=owner_clinician)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([admin_clinician, owner, owner_clinician, post])

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200
    values = _picker_values(response.text, _CLINICIAN_FIELD[kind])
    assert str(owner_clinician.clinician_affiliations[0].id) in values
    assert str(admin_clinician.clinician_affiliations[0].id) not in values


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
async def test_edit_form_keeps_current_practice_owner_does_not_own(
    kind: str,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """An org rep can post under an affiliated clinician they don't own
    (Claim B path). The edit picker must still offer — and select — the
    post's current practice, so saving doesn't silently re-point it."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    foreign_clinician = make_clinician_with_org(
        owner_id=other.id, practice_name="Group Practice"
    )
    foreign_clinician.id = uuid.uuid4()
    post = _post_on_affiliation(
        kind, owner_id=logged_in_user.id, clinician=foreign_clinician
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([other, foreign_clinician, post])

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200
    aff_id = str(foreign_clinician.clinician_affiliations[0].id)
    select = HTMLParser(response.text).css_first(
        f'select[name="{_CLINICIAN_FIELD[kind]}"]'
    )
    selected = [o for o in select.css("option") if "selected" in o.attributes]
    assert [o.attributes.get("value") for o in selected] == [aff_id]


async def test_admin_edit_intake_form_lists_owner_programs_not_admins(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Same owner-not-viewer rule for the program-intake picker."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    admin_org = make_organization_row(owner_id=logged_in_user.id, name="Admin Org")
    admin_program = make_program(
        owner_id=logged_in_user.id, org_id=admin_org.id, name="Admin Program"
    )
    admin_program.id = uuid.uuid4()
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    owner_org = make_organization_row(owner_id=owner.id, name="Owner Org")
    owner_program = make_program(
        owner_id=owner.id, org_id=owner_org.id, name="Owner Program"
    )
    owner_program.organization = owner_org
    post = _intake_post(owner_id=owner.id, org_id=owner_org.id, program=owner_program)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all(
                [admin_org, admin_program, owner, owner_org, owner_program, post]
            )

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200
    values = _picker_values(response.text, "program_id")
    assert str(owner_program.id) in values
    assert str(admin_program.id) not in values
