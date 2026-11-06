"""Tests for the section-shape macros in ``_shared/sections.html``.

``fact`` + ``facts_block`` are the canonical pair for rendering a
labeled key/value rows panel — used by every list-card body, every
detail-page card body, and a few form-page confirmation surfaces.
``fact_list`` is the multi-value variant: same row contract, but the
value stacks one item per line (a ``<ul class="fact-values">``) instead
of being comma-joined — the detail-page treatment for "a list of
things". Domain templates must compose these macros instead of
hand-rolling the ``<section class="entity-facts"><dl>…</dl></section>``
chrome (per #1193's component-library rule).
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selectolax.parser import HTMLParser


def _make_env() -> Environment:
    stub = DictLoader({})
    framework = FileSystemLoader(
        str(Path(__file__).resolve().parents[1])
    )  # src/framework/templates
    return Environment(loader=ChoiceLoader([stub, framework]))


def _render(env: Environment, body: str) -> str:
    template = (
        '{%- from "_shared/sections.html" import fact, fact_list, facts_block -%}'
        "{% call facts_block() %}" + body + "{% endcall %}"
    )
    return env.from_string(template).render()


def test_facts_block_emits_canonical_section_and_dl_wrapper() -> None:
    """The wrapper is a single ``<section class="entity-facts">``
    containing a single ``<dl>``. Domain templates rely on the
    ``.entity-facts`` class for Pico styling and the grid layout."""
    env = _make_env()
    html = _render(env, "{{ fact('npi', 'NPI', '1234567890') }}")
    tree = HTMLParser(html)
    sections = tree.css("section.entity-facts")
    assert len(sections) == 1, "Expected one <section class='entity-facts'>"
    dls = sections[0].css("dl")
    assert len(dls) == 1, "Expected one <dl> directly inside the section"


def test_facts_block_renders_caller_rows_inside_the_dl() -> None:
    """Caller-supplied ``fact(...)`` rows render as ``<div data-fact>``
    wrappers inside the ``<dl>``, in caller-supplied order."""
    env = _make_env()
    html = _render(
        env,
        "{{ fact('npi', 'NPI', '1234567890') }}"
        "{{ fact('state', 'State served', 'NY') }}",
    )
    tree = HTMLParser(html)
    rows = tree.css("section.entity-facts > dl > div[data-fact]")
    assert [r.attributes.get("data-fact") for r in rows] == ["npi", "state"]


def test_fact_list_stacks_values_one_per_line() -> None:
    """``fact_list`` renders its values as a bullet-less
    ``<ul class="fact-values">`` of ``<li>``s inside the ``<dd>`` — the
    detail-page counterpart to ``fact``'s comma-joined value. The
    ``data-fact`` key and ``<dt>`` label match ``fact`` so the test
    selector and label are unchanged; only the value layout differs."""
    env = _make_env()
    html = _render(
        env,
        "{{ fact_list('services', 'Seeking', ['Therapy', 'Meds', 'Groups']) }}",
    )
    tree = HTMLParser(html)
    row = tree.css_first('div[data-fact="services"]')
    assert row is not None
    items = row.css("dd ul.fact-values > li")
    assert [li.text(strip=True) for li in items] == ["Therapy", "Meds", "Groups"]


def test_fact_list_single_value_renders_one_line() -> None:
    """A length-1 list renders a single ``<li>`` — callers can route any
    "list of things" through ``fact_list`` without special-casing
    length 1."""
    env = _make_env()
    html = _render(env, "{{ fact_list('age', 'Age', ['Adult']) }}")
    tree = HTMLParser(html)
    items = tree.css('div[data-fact="age"] dd ul.fact-values > li')
    assert [li.text(strip=True) for li in items] == ["Adult"]


def test_facts_grid_groups_put_dl_directly_in_the_grid_section() -> None:
    """`facts_grid` is the `<section class="entity-facts facts-grid">`
    panel; `fact_group` drops a full-width `<h2>` and `fact_rows` a `<dl>`,
    both as DIRECT children of it. The `<dl>`-as-direct-child structure is
    what lets it subgrid the shared tracks without collapsing any wrapper
    via `display: contents` (so the section keeps its normal box) — this
    test pins that contract so a future refactor can't silently
    reintroduce an intervening wrapper."""
    env = _make_env()
    template = (
        '{%- from "_shared/sections.html" import fact, facts_grid, fact_group, fact_rows -%}'
        "{% call facts_grid() %}"
        '{{ fact_group("Logistics") }}'
        '{% call fact_rows() %}{{ fact("state", "State", "NY") }}{% endcall %}'
        '{{ fact_group("Coverage") }}'
        '{% call fact_rows() %}{{ fact("plan", "Plan", "PPO") }}{% endcall %}'
        "{% endcall %}"
    )
    tree = HTMLParser(env.from_string(template).render())
    grid = tree.css_first("section.entity-facts.facts-grid")
    assert grid is not None
    # h2 headings and dls are DIRECT children of the grid section.
    heads = [h.text(strip=True) for h in grid.css("section.facts-grid > h2.fact-group")]
    assert heads == ["Logistics", "Coverage"], heads
    dls = grid.css("section.facts-grid > dl")
    assert len(dls) == 2, "each group's <dl> must be a direct child of the grid"
    # The rows live inside their group's dl.
    assert dls[0].css_first("div[data-fact] dt").text(strip=True) == "State"


def test_facts_block_empty_body_still_emits_wrapper() -> None:
    """An empty caller body still emits the wrapper chrome — relevant
    for templates that gate every row behind an ``{% if %}`` and the
    gate happens to be false at render time. (The wrapper is cheap; a
    missing wrapper would break the surrounding card layout.)"""
    env = _make_env()
    html = _render(env, "")
    tree = HTMLParser(html)
    assert tree.css_first("section.entity-facts dl") is not None
    assert tree.css_first("section.entity-facts dl div[data-fact]") is None


def test_facts_block_no_record_marks_the_section() -> None:
    """``no_record=True`` puts ``data-no-record`` on the wrapper — the
    attribute the session-recording snippet treats as "never capture this
    subtree". Off by default so ordinary fact blocks stay recordable."""
    env = _make_env()
    template = (
        '{%- from "_shared/sections.html" import fact, facts_block -%}'
        "{% call facts_block(no_record=True) %}{{ fact('a', 'A', 'x') }}{% endcall %}"
    )
    tree = HTMLParser(env.from_string(template).render())
    section = tree.css_first("section.entity-facts")
    assert "data-no-record" in section.attributes
    assert section.css_first("div[data-fact='a']") is not None

    default = HTMLParser(_render(env, "{{ fact('a', 'A', 'x') }}"))
    assert "data-no-record" not in default.css_first("section.entity-facts").attributes
