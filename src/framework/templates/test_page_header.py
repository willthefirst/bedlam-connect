"""Tests for the page top-chrome: the page-header band
(``_shared/_page_header.html``), the breadcrumb bar (``_shared/_breadcrumb.html``),
and the page toolbar (``_shared/_toolbar.html``).

The chrome is three full-width bands stacked above the content, each a
body-level layout row:

  1. ``<header class="page-header">`` — the primary nav only. Its inner
     ``.container`` centers and caps the nav at Pico's container max-width;
     the band's ``border-bottom`` spans the full page.
  2. ``<nav class="breadcrumb-bar">`` — its OWN body-level band (a sibling of
     ``<header>``/``<main>``/``<footer>``, NOT nested in the header). Always
     shows a real, visible crumb on authenticated pages — a page-supplied
     breadcrumb when set, else a default "Home" crumb. No hidden placeholder.
  3. The page ``<h1>`` + actions toolbar, which lives at the top of
     ``<main>`` (not in the band).

These tests render the generic view-type templates (which compose the chrome
via ``base.html``) and pin that structure. A second group pins the CSS rules
the toolbar's no-wrap/truncation guarantees depend on. A third group pins the
**body-layout invariant**: ``base.html`` emits ``<header>``, the breadcrumb
``<nav>``, ``<main>``, ``<footer>`` as the layout rows of the body flex column,
followed only by locked-CTA popovers and an init script.
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment
from selectolax.parser import HTMLParser

from src.framework.templates._test_env import add_child as _add_child
from src.framework.templates._test_env import make_test_env as _make_env_impl

_CSS_PATH = Path(__file__).parent.parent / "static" / "css" / "framework.css"


def _make_env() -> Environment:
    return _make_env_impl()


class _RequestStub:
    class _Url:
        path = "/"

    url = _Url()
    query_params: dict[str, str] = {}


def _request_stub(path: str = "/") -> _RequestStub:
    stub = _RequestStub()
    stub.url = _RequestStub._Url()
    stub.url.path = path
    stub.query_params = {}
    return stub


def _render(env: Environment, name: str, **ctx: object) -> str:
    base: dict[str, object] = dict(
        request=_request_stub(), is_authenticated=False, is_development=False
    )
    base.update(ctx)
    return env.get_template(name).render(**base)


_DETAIL_STUB = """
    {% extends "views/detail.html" %}
    {% set entity_name = "clinician" %}
    {% block resource_label %}Clinicians{% endblock %}
    {% block current_label %}Sunrise Therapy{% endblock %}
    {% block content %}<p>body</p>{% endblock %}
"""

_LIST_STUB = """
    {% extends "views/list.html" %}
    {% block resource_label %}Clinicians{% endblock %}
    {% block content %}<p>body</p>{% endblock %}
"""


def test_detail_toolbar_in_main_and_breadcrumb_is_its_own_band() -> None:
    """A detail page's toolbar `<h1>` lives in `<main>` (not the page-header
    band), and its breadcrumb is its OWN body-level `<nav class="breadcrumb-bar">`
    — not nested inside `header.page-header`."""
    env = _make_env()
    _add_child(env, "stub.html", _DETAIL_STUB)
    tree = HTMLParser(_render(env, "stub.html", is_authenticated=True))

    # Toolbar H1 is in <main>, not the band.
    assert tree.css_first("header.page-header div.toolbar h1") is None
    assert tree.css_first("main div.toolbar h1") is not None

    # Breadcrumb is a body-level band, not inside the header.
    assert tree.css_first("header.page-header nav.breadcrumb-bar") is None
    bar = tree.css_first("body > nav.breadcrumb-bar")
    assert bar is not None
    assert bar.attributes.get("aria-label") == "breadcrumb"
    # Full Pico chain in a `.container > ul`: Home › Collection › <resource>.
    crumbs = [li.text(strip=True) for li in bar.css("div.container ul li")]
    assert crumbs == ["Home", "Clinicians", "Sunrise Therapy"]


def test_list_page_shows_visible_home_breadcrumb_no_placeholder() -> None:
    """Top-level list pages carry no page-specific breadcrumb, so the bar falls
    back to a real, visible "Home" crumb — never the old hidden placeholder.
    The toolbar `<h1>` still renders (in `<main>`)."""
    env = _make_env()
    _add_child(env, "stub.html", _LIST_STUB)
    tree = HTMLParser(_render(env, "stub.html", is_authenticated=True))

    bar = tree.css_first("body > nav.breadcrumb-bar")
    assert bar is not None
    crumbs = bar.css("div.container ul li")
    # Home links to `/` (the single home entry point); the collection
    # itself is the current leaf.
    assert [li.text(strip=True) for li in crumbs] == ["Home", "Clinicians"]
    assert crumbs[0].css_first("a").attributes.get("href") == "/"
    assert crumbs[-1].css_first("a") is None  # current page, no link
    # The hidden-placeholder mechanism is gone entirely.
    assert tree.css_first(".page-header-crumb-placeholder") is None
    assert tree.css_first("main div.toolbar h1") is not None


def test_anonymous_pages_have_no_breadcrumb_band() -> None:
    """Anonymous pages (no page-supplied crumb, not authenticated) render no
    breadcrumb band at all — the Home fallback is authenticated-only."""
    env = _make_env()
    _add_child(env, "stub.html", _LIST_STUB)
    tree = HTMLParser(_render(env, "stub.html", is_authenticated=False))
    assert tree.css_first("nav.breadcrumb-bar") is None


def test_band_owns_a_boundary_and_no_hr_anywhere() -> None:
    """No `<hr>` lives in the band or in `<main>` — dividers are the
    `border-bottom`s on `.page-header` / `.breadcrumb-bar` (pinned via CSS
    regex below)."""
    env = _make_env()
    _add_child(env, "stub.html", _DETAIL_STUB)
    tree = HTMLParser(_render(env, "stub.html"))

    band = tree.css_first("header.page-header")
    assert band is not None
    assert len(band.css("hr")) == 0

    main = tree.css_first("main")
    assert main is not None
    assert len(main.css("hr")) == 0


def test_every_toolbar_reserves_the_action_row_height() -> None:
    """Each toolbar renders a hidden, non-interactive reserve `<button>` so the
    action-row height is constant whether or not a page has real actions. The
    toolbar now lives in `<main>`; the reserve is aria-hidden and removed from
    the tab order so it's chrome-only."""
    env = _make_env()
    _add_child(env, "liststub.html", _LIST_STUB)
    _add_child(env, "detailstub.html", _DETAIL_STUB)
    for name in ("liststub.html", "detailstub.html"):
        tree = HTMLParser(_render(env, name))
        reserve = tree.css_first("main div.toolbar button.toolbar-reserve")
        assert reserve is not None, f"{name}: toolbar must render the reserve button"
        assert reserve.attributes.get("aria-hidden") == "true"
        assert reserve.attributes.get("tabindex") == "-1"


# Context for the authenticated-chrome tests: only sets `is_authenticated=True`
# to exercise the authed path.
_AUTHED_CTX: dict[str, object] = dict(is_authenticated=True)


def test_body_layout_rows_are_header_breadcrumb_main_footer() -> None:
    """`base.html` emits the four full-width layout rows of the body flex
    column — `<header>`, the breadcrumb `<nav>`, `<main>`, `<footer>` — in
    order, followed only by locked-CTA `<div popover>` elements and an init
    `<script>`."""
    env = _make_env()
    _add_child(env, "liststub.html", _LIST_STUB)
    _add_child(env, "detailstub.html", _DETAIL_STUB)
    for name in ("liststub.html", "detailstub.html"):
        tree = HTMLParser(_render(env, name, **_AUTHED_CTX))
        top_level = [n.tag for n in tree.css("body > *")]
        assert top_level[:4] == [
            "header",
            "nav",
            "main",
            "footer",
        ], f"{name}: {top_level}"
        # The breadcrumb row is the body-level breadcrumb bar.
        assert tree.css_first("body > nav.breadcrumb-bar") is not None, name
        # Remaining children are only locked-CTA popovers and the init script.
        assert all(
            t in ("div", "script") for t in top_level[4:]
        ), f"{name}: unexpected body tail elements: {top_level[4:]}"
        for div in tree.css("body > div"):
            assert "popover" in div.attributes, f"{name}: non-popover div in body"


def test_authenticated_nav_has_post_link_and_avatar_dropdown() -> None:
    """The authenticated primary nav is the canonical Pico shape: a brand `<ul>`
    (→ the posts collection) and an actions `<ul>` with a `Post` link (→ the
    create form, a plain link fronted by a leading `plus` glyph) and a Pico
    `<details class="dropdown">` profile menu. The nav has no `id` hook — it's
    the `aria-label="Primary"` landmark."""
    env = _make_env()
    _add_child(env, "detailstub.html", _DETAIL_STUB)
    tree = HTMLParser(_render(env, "detailstub.html", **_AUTHED_CTX))

    nav = tree.css_first('nav[aria-label="Primary"]')
    assert nav is not None
    # The id hook was removed in favor of the landmark.
    assert nav.attributes.get("id") is None

    # Brand → `/` (the single home entry point), inside the first <ul>.
    brand = nav.css_first("ul li a strong")
    assert brand is not None and brand.text(strip=True) == "Bedlam Connect"
    assert brand.parent.attributes.get("href") == "/"

    # `Post` is a plain link to the create form, fronted by a `plus` glyph
    # (aria-hidden, so the label text is still just "Post").
    post_links = [a for a in nav.css("a") if a.text(strip=True) == "Post"]
    assert len(post_links) == 1, "exactly one `Post` link expected"
    post = post_links[0]
    assert post.attributes.get("href") == "/posts/form"
    assert post.attributes.get("role") is None, "`Post` must be a plain link"
    icon = post.css_first("i.icon-plus")
    assert icon is not None, "`Post` button must lead with a plus icon"
    assert icon.attributes.get("aria-hidden") == "true"

    # Profile menu is a Pico dropdown.
    dropdown = nav.css_first("details.dropdown#nav-menu")
    assert dropdown is not None, "profile menu must be a `<details class='dropdown'>`"


def test_avatar_menu_items_are_my_posts_account_sign_out() -> None:
    """For a non-admin viewer the profile dropdown's items are exactly
    My posts (→ the viewer's own posts via `?owner=me`), Account (→ the
    self user page), and Sign out (`hx-post`). "Saved" is deferred and
    must not appear. Admins get one extra item — see
    `test_avatar_menu_shows_audit_log_for_admins_only`."""
    env = _make_env()
    _add_child(env, "detailstub.html", _DETAIL_STUB)
    tree = HTMLParser(_render(env, "detailstub.html", **_AUTHED_CTX))

    menu = tree.css_first("details.dropdown#nav-menu")
    assert (
        menu is not None
    ), "profile `<details class='dropdown' id='nav-menu'>` missing"
    items = menu.css("ul li a")
    labels = [a.text(strip=True) for a in items]
    assert labels == ["My posts", "Account", "Sign out"]
    assert "Saved" not in labels

    by_label = {a.text(strip=True): a for a in items}
    assert by_label["My posts"].attributes.get("href") == "/posts?owner=me"
    assert by_label["Account"].attributes.get("href") == "/users/me"
    assert by_label["Sign out"].attributes.get("hx-post") == "/auth/sign-out"


def test_avatar_menu_shows_audit_log_for_admins_only() -> None:
    """Superusers get Audit log (→ `/admin/audit`) and Admin data
    (→ `/admin/data/`, the Datasette observability queries) between
    Account and Sign out. The gate is the `is_admin` chrome scalar from
    `base_context`, which a handler cannot override — so the item can
    never render for a non-admin (whose exact item set is pinned by
    `test_avatar_menu_items_are_my_posts_account_sign_out`)."""
    env = _make_env()
    _add_child(env, "detailstub.html", _DETAIL_STUB)
    tree = HTMLParser(_render(env, "detailstub.html", is_admin=True, **_AUTHED_CTX))

    menu = tree.css_first("details.dropdown#nav-menu")
    assert menu is not None
    items = menu.css("ul li a")
    labels = [a.text(strip=True) for a in items]
    assert labels == ["My posts", "Account", "Audit log", "Admin data", "Sign out"]

    by_label = {a.text(strip=True): a for a in items}
    assert by_label["Audit log"].attributes.get("href") == "/admin/audit"
    assert by_label["Admin data"].attributes.get("href") == "/admin/data/"


def test_anonymous_nav_is_brand_only() -> None:
    """Anonymous visitors get the brand link only — no `Post` link and no
    profile dropdown."""
    env = _make_env()
    _add_child(env, "detailstub.html", _DETAIL_STUB)
    tree = HTMLParser(_render(env, "detailstub.html", is_authenticated=False))

    nav = tree.css_first('nav[aria-label="Primary"]')
    assert nav is not None
    assert nav.css_first("details.dropdown#nav-menu") is None
    assert [a for a in nav.css("a") if a.text(strip=True) == "Post"] == []
    # The brand link is still present.
    assert nav.css_first("a strong").text(strip=True) == "Bedlam Connect"


def test_css_pins_no_wrap_truncation_and_full_width_dividers() -> None:
    """Pin the CSS the chrome's guarantees rest on: the toolbar actions cell
    never wraps (so it doesn't grow), the toolbar `<h1>` truncates rather than
    wraps, and both the header and breadcrumb bands own full-width
    `border-bottom` dividers."""
    css = _CSS_PATH.read_text()

    assert re.search(
        r"\.toolbar-right\b[^{]*\{[^}]*flex-wrap:\s*nowrap", css, re.DOTALL
    ), ".toolbar-right must declare `flex-wrap: nowrap` so actions don't grow"

    h1_rule = re.search(r"\.toolbar\s+h1\s*\{([^}]*)\}", css, re.DOTALL)
    assert h1_rule is not None, ".toolbar h1 must have a rule"
    h1_body = h1_rule.group(1)
    for decl in ("text-overflow: ellipsis", "white-space: nowrap", "min-width: 0"):
        assert (
            decl in h1_body
        ), f".toolbar h1 must declare `{decl}` so the title truncates"

    assert re.search(
        r"\.page-header\s*\{[^}]*border-bottom:\s*1px\s+solid", css, re.DOTALL
    ), ".page-header must own a full-width `border-bottom` divider"
    assert re.search(
        r"\.breadcrumb-bar\s*\{[^}]*border-bottom:\s*1px\s+solid", css, re.DOTALL
    ), ".breadcrumb-bar must own a full-width `border-bottom` divider"

    # The action-row reserve: a hidden button sharing the H1's grid cell.
    h1_grid = re.search(r"\.toolbar\s+h1\s*\{([^}]*)\}", css, re.DOTALL).group(1)
    assert "grid-row: 1" in h1_grid and "grid-column: 1" in h1_grid, (
        ".toolbar h1 must be explicitly placed at row 1 / col 1 so the reserve "
        "button overlaps it"
    )
    reserve_rule = re.search(r"\.toolbar-reserve\s*\{([^}]*)\}", css, re.DOTALL)
    assert reserve_rule is not None, ".toolbar-reserve must have a rule"
    reserve_body = reserve_rule.group(1)
    for decl in ("grid-row: 1", "grid-column: 1", "visibility: hidden"):
        assert decl in reserve_body, f".toolbar-reserve must declare `{decl}`"
