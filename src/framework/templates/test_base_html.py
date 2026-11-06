"""Tests for `base.html` — the document-shell template every page extends.

These pin contracts that live on the `<head>` itself (not on a particular
view-type chrome): the head scripts must not render-block the initial
paint. `_page_header.html` band tests live in `test_page_header.py`;
view-type chrome tests live in `test_views.py`.
"""

from __future__ import annotations

from jinja2 import Environment
from selectolax.parser import HTMLParser

from src.framework.templates._test_env import add_child as _add_child
from src.framework.templates._test_env import make_test_env as _make_env_impl


def _make_env() -> Environment:
    return _make_env_impl()


class _RequestStub:
    class _Url:
        path = "/"

    url = _Url()
    query_params: dict[str, str] = {}


def _request_stub() -> _RequestStub:
    return _RequestStub()


_STUB = """
    {% extends "base.html" %}
    {% block content %}<p>body</p>{% endblock %}
"""


def _render(
    observability_frontend: object | None = None,
    storyteller_frontend: object | None = None,
    current_user_id: object | None = None,
) -> str:
    env = _make_env()
    _add_child(env, "stub.html", _STUB)
    return env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=current_user_id is not None,
        is_development=False,
        observability_frontend=observability_frontend,
        storyteller_frontend=storyteller_frontend,
        current_user_id=current_user_id,
    )


_STORYTELLER_FRONTEND = {"endpoint": "/storyteller", "site_key": "site-key-1"}


_SENTRY_FRONTEND = {
    "provider": "sentry",
    "dsn": "https://example@sentry.io/1",
    "environment": "test",
    "release": "abc123",
    "traces_sample_rate": 0.1,
    "replays_session_sample_rate": 0.0,
    "replays_on_error_sample_rate": 0.0,
}


def test_head_scripts_carry_defer_so_first_paint_is_not_render_blocked() -> None:
    """Every external `<script src=...>` inside `<head>` must declare
    `defer` (or `async`) — otherwise the parser blocks while the
    script downloads + executes, delaying first paint on every page.

    htmx attaches its initial DOM scan to `DOMContentLoaded`, so
    `defer` is the supported pattern: scripts run in document order
    after parsing completes but before that event fires.

    Asserted under both the no-observability render AND the
    sentry-on render — the Sentry loader is a separate render-blocking
    surface gated by `observability_frontend`.

    See https://developer.chrome.com/docs/performance/insights/render-blocking.
    """
    for label, html in (
        ("no observability", _render(None)),
        ("sentry", _render(_SENTRY_FRONTEND)),
        ("storyteller", _render(storyteller_frontend=_STORYTELLER_FRONTEND)),
    ):
        tree = HTMLParser(html)
        head = tree.css_first("head")
        assert head is not None

        offenders = [
            node.attributes.get("src")
            for node in head.css("script")
            if node.attributes.get("src")
            and "defer" not in node.attributes
            and "async" not in node.attributes
        ]
        assert not offenders, (
            f"[{label}] head scripts missing defer/async (each adds "
            f"render-blocking latency to every page): {offenders}"
        )


def _storyteller_scripts(html: str) -> tuple[list[str], str]:
    """(external storyteller script srcs, inline init source) from <head>."""
    head = HTMLParser(html).css_first("head")
    assert head is not None
    srcs = [
        n.attributes.get("src", "")
        for n in head.css("script")
        if "storyteller" in (n.attributes.get("src") or "")
    ]
    inline = "\n".join(
        n.text() for n in head.css("script") if "storyteller." in (n.text() or "")
    )
    return srcs, inline


def test_storyteller_snippet_absent_without_a_site_key() -> None:
    """`storyteller_frontend=None` (no `STORYTELLER_SITE_KEY`) → no script
    tag and no init — the page must not even load the 80 KB snippet."""
    srcs, inline = _storyteller_scripts(_render())
    assert srcs == [] and inline == ""


def test_storyteller_snippet_inits_with_endpoint_and_site_key() -> None:
    """With a site key the snippet loads from our static mount and the
    DOMContentLoaded init passes the configured endpoint + site key, then
    calls `start()` (which itself defers to the service's kill switch)."""
    srcs, inline = _storyteller_scripts(
        _render(storyteller_frontend=_STORYTELLER_FRONTEND)
    )
    assert srcs == ["/static/fw/js/storyteller.js"]
    assert 'endpoint: "/storyteller"' in inline
    assert 'siteKey: "site-key-1"' in inline
    assert "storyteller.start()" in inline
    assert "storyteller.identify(" not in inline, "anonymous: no identify"


def test_storyteller_snippet_identifies_the_signed_in_user() -> None:
    """Signed-in viewers are `identify()`d by id so stories can say which
    member a visit belongs to."""
    _, inline = _storyteller_scripts(
        _render(storyteller_frontend=_STORYTELLER_FRONTEND, current_user_id="u-42")
    )
    assert 'storyteller.identify("u-42")' in inline
    # Order matters: init → identify → start.
    assert inline.index("init(") < inline.index("identify(") < inline.index("start(")


def test_meta_description_present_with_default_copy() -> None:
    """`base.html` always emits `<meta name="description">`. Without
    it, search engines and link-preview crawlers fall back to the
    first sentence of the body — usually nav chrome on this app. The
    default sentence applies to every page that doesn't override the
    `meta_description` block.
    """
    tree = HTMLParser(_render())
    descriptions = [
        node
        for node in tree.css("meta")
        if node.attributes.get("name") == "description"
    ]
    assert len(descriptions) == 1
    content = descriptions[0].attributes.get("content") or ""
    assert "Bedlam Connect" in content
    assert len(content) > 30


def test_default_footer_is_a_centered_support_note() -> None:
    """The default footer is a single `<p class="footer-note">` support
    note — plain flowing text with one `mailto:` contact, NOT a `.meta`
    flex list. Flowing text stays centered by the `footer { text-align:
    center }` rule at every width, which is the whole point of dropping the
    `.meta` machinery (that stacked/left-aligned the footer on narrow
    viewports). Pins the contact address and the "no flex row here"
    contract at the site-wide chrome level."""
    tree = HTMLParser(_render())
    footer = tree.css_first("footer")
    assert footer is not None
    note = footer.css_first("p.footer-note")
    assert note is not None
    # Flowing text, not the `.meta` flex row (which needed per-breakpoint
    # re-centering) and no middot separators.
    assert footer.css_first("p.meta") is None
    assert not note.css("span.meta-sep")
    contact = note.css_first("a[href^='mailto:']")
    assert contact is not None
    # Copy + pre-filled mailto come from the shared `_shared/support.html`
    # macro (see `_shared/test_support.py`); the footer just wraps it. Assert
    # the address is right and the prefill rode along.
    href = contact.attributes.get("href") or ""
    assert href.startswith("mailto:help@bedlamconnect.com?")
    assert "subject=" in href and "body=" in href


def test_preconnect_to_each_vendor_cdn() -> None:
    """Every cross-origin CDN we fetch from in `<head>` needs a
    matching `<link rel="preconnect">` so the TCP+TLS handshake fires
    in parallel with HTML parsing — otherwise the first request to
    that origin pays the full RTT serially.

    Currently three: Pico (jsdelivr), htmx + extensions (unpkg),
    Sentry SDK (sentry-cdn).
    """
    tree = HTMLParser(_render())
    preconnects = {
        node.attributes.get("href") for node in tree.css('link[rel="preconnect"]')
    }
    assert "https://cdn.jsdelivr.net" in preconnects
    assert "https://unpkg.com" in preconnects
    assert "https://browser.sentry-cdn.com" in preconnects


def test_sentry_bundle_picks_non_tracing_when_traces_disabled() -> None:
    """`traces_sample_rate=0` means we don't need
    `Sentry.browserTracingIntegration()` — and that integration only
    ships in the `bundle.tracing.*` builds (~14 KiB larger). The
    template must drop to `bundle.min.js` in that case (or
    `bundle.replay.min.js` when replays are enabled).
    """
    no_traces = {**_SENTRY_FRONTEND, "traces_sample_rate": 0.0}
    tree = HTMLParser(_render(no_traces))
    srcs = [node.attributes.get("src", "") for node in tree.css("script")]
    sentry_srcs = [s for s in srcs if "sentry-cdn.com" in s]
    assert len(sentry_srcs) == 1
    assert "/bundle.min.js" in sentry_srcs[0]
    assert "tracing" not in sentry_srcs[0]

    traces_on = {**_SENTRY_FRONTEND, "traces_sample_rate": 0.1}
    tree = HTMLParser(_render(traces_on))
    sentry_srcs = [
        s
        for s in (n.attributes.get("src", "") for n in tree.css("script"))
        if "sentry-cdn.com" in s
    ]
    assert "/bundle.tracing.min.js" in sentry_srcs[0]
