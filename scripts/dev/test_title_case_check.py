"""Tests for `scripts/dev/title_case_check.py`.

The checker enforces sentence case on Markdown headers, HTML/Jinja headings,
and similar prose. Code embedded in Markdown fenced code blocks is NOT prose
and must be skipped — otherwise Python `# comments` inside a fence get
mistaken for level-1 headings, which causes spurious lint failures and was
the source of recurring friction during agent-driven doc edits.

For HTML/Jinja the checker parses the document with selectolax and lints
only text nodes inside an allowlist of content elements (plus a few
user-facing attribute values). The previous regex-over-raw-text approach
couldn't tell text nodes from attribute values, which produced false
positives on inline ``style="..."`` and required a hand-curated CSS
property allowlist; those tests live below.
"""

import textwrap
from pathlib import Path

from scripts.dev.title_case_check import TitleCaseChecker


def _write_md(tmp_path: Path, body: str) -> Path:
    file = tmp_path / "doc.md"
    file.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return file


def _write_html(tmp_path: Path, body: str, name: str = "page.html") -> Path:
    file = tmp_path / name
    file.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return file


def _check(file: Path) -> list:
    checker = TitleCaseChecker(fix_mode=False, respect_gitignore=False)
    return checker.check_file(file)


def test_fenced_code_block_python_comments_are_not_treated_as_headings(tmp_path):
    """A Python comment inside a ```python``` fence must NOT be flagged as
    a level-1 Markdown heading.

    This regression exists because the checker scans line-by-line for `#`
    prefixes; without fence-awareness it sees `# Some comment` inside code
    as a heading and demands sentence-case it would never naturally have.
    """
    file = _write_md(
        tmp_path,
        """
        # Real heading

        Some prose.

        ```python
        # Register me before users so that "/users/me" matches the literal
        # handler rather than being parsed as a UUID by "/users/{user_id}".
        app.include_router(me.me_router_instance)
        ```

        More prose.
        """,
    )

    checker = TitleCaseChecker(fix_mode=False, respect_gitignore=False)
    violations = checker.check_file(file)

    fenced_violations = [v for v in violations if "Register" in v["original"]]
    assert fenced_violations == [], (
        f"Python comments inside fenced code should not be flagged, got: "
        f"{fenced_violations}"
    )


def test_fenced_code_block_does_not_swallow_following_headings(tmp_path):
    """The fence-tracking state must close on the second triple-backtick so
    that real Markdown headings *after* the fence are still checked."""
    file = _write_md(
        tmp_path,
        """
        # Real heading

        ```python
        # Comment that should be skipped
        ```

        ## badly cased heading after fence
        """,
    )

    checker = TitleCaseChecker(fix_mode=False, respect_gitignore=False)
    violations = checker.check_file(file)

    after_fence = [v for v in violations if "badly cased" in v["original"]]
    assert len(after_fence) == 1, (
        "A miscased heading following a fenced code block should still be "
        f"caught, got violations: {violations}"
    )


def test_tilde_fenced_code_block_is_also_skipped(tmp_path):
    """Markdown supports both ``` and ~~~ as fence delimiters."""
    file = _write_md(
        tmp_path,
        """
        # Real heading

        ~~~python
        # MUST be ignored
        ~~~
        """,
    )

    checker = TitleCaseChecker(fix_mode=False, respect_gitignore=False)
    violations = checker.check_file(file)

    fenced_violations = [v for v in violations if "MUST" in v["original"]]
    assert fenced_violations == [], (
        f"Comments inside ~~~ fenced blocks should be skipped, got: "
        f"{fenced_violations}"
    )


def test_real_heading_outside_any_fence_is_still_checked(tmp_path):
    """Sanity: the fix doesn't break the checker entirely."""
    file = _write_md(
        tmp_path,
        """
        # this Heading IS Wrongly cased

        Some prose.
        """,
    )

    checker = TitleCaseChecker(fix_mode=False, respect_gitignore=False)
    violations = checker.check_file(file)

    assert any(
        "Wrongly" in v["original"] for v in violations
    ), f"A real miscased heading must still be flagged, got: {violations}"


# ---------------------------------------------------------------------------
# Parsed-mode HTML/Jinja checker
#
# These cases used to be handled — partially and unreliably — by line-based
# regex plus an ad-hoc CSS-property allowlist. The checker now parses the
# document and lints only structurally identified prose, which is what these
# tests pin down. They are also the regression baseline for the rewrite: if
# any of these starts firing again, a parser bug has crept in.
# ---------------------------------------------------------------------------


def test_inline_style_no_false_positive(tmp_path):
    """Inline ``style="..."`` is an attribute value, not prose. The previous
    regex approach matched ``gap:`` from CSS as a "label needing
    title-case", which is exactly the bug this rewrite eliminates."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <ul style="display: flex; gap: 1rem; margin: 0">
          <li>Items</li>
        </ul>
        </body></html>
        """,
    )
    violations = _check(file)
    assert not any(
        v["original"].lower().startswith(("gap", "display", "margin"))
        for v in violations
    ), f"CSS-in-style should not be linted, got: {violations}"


def test_attribute_names_and_unrelated_values_ignored(tmp_path):
    """``href``, ``class``, ``id``, ``data-*`` and tag names themselves are
    never prose. Only the small allowlist of user-facing attributes
    (``alt``, ``title``, ``placeholder``, ``aria-label``,
    ``aria-description``) is linted."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <a href="/Posts" class="Foo Bar" id="MyId" data-thing="X Y">link</a>
        </body></html>
        """,
    )
    violations = _check(file)
    bad = [
        v for v in violations if v["original"] in {"/Posts", "Foo Bar", "MyId", "X Y"}
    ]
    assert not bad, f"Non-allowlisted attribute values must not lint, got: {bad}"


def test_lintable_attribute_value_is_checked(tmp_path):
    file = _write_html(tmp_path, "<html><body><img alt='Profile Photo'></body></html>")
    violations = _check(file)
    assert any(
        v["original"] == "Profile Photo" for v in violations
    ), f"alt attribute value should lint, got: {violations}"


def test_text_node_inside_link_is_linted(tmp_path):
    file = _write_html(
        tmp_path,
        "<html><body><a href='/x'>Posts Page</a></body></html>",
    )
    violations = _check(file)
    assert any(v["original"] == "Posts Page" for v in violations)


def test_jinja_in_attribute_does_not_break_parsing(tmp_path):
    """A Jinja expression inside an attribute value (``href="{{ url }}"``)
    must not derail the parser or cause the surrounding prose to be
    mis-linted. The expression is replaced with a sentinel before parsing
    and the link text is what we actually want to check."""
    file = _write_html(
        tmp_path,
        """
        {% extends "base.html" %}
        {% block content %}
        <a href="{{ url_for('foo') }}">View Post Now</a>
        {% endblock %}
        """,
        name="page.jinja",
    )
    violations = _check(file)
    originals = {v["original"] for v in violations}
    assert "View Post Now" in originals, f"Got: {violations}"
    # The sentinel must never leak into a violation.
    assert not any("JINJAPLACEHOLDER" in v["original"] for v in violations)


def test_jinja_substitution_in_text_is_skipped(tmp_path):
    """When prose contains a Jinja expression ``{{ x }}``, we cannot judge
    the rendered case — the whole text is skipped rather than flagged
    against the placeholder."""
    file = _write_html(
        tmp_path,
        "<html><body><p>Welcome, {{ user.name }}!</p></body></html>",
    )
    violations = _check(file)
    assert violations == [], f"Jinja-bearing text should be skipped, got: {violations}"


def test_script_and_style_subtrees_skipped(tmp_path):
    """``<script>`` and ``<style>`` content is code, not prose. The walker
    must never descend into either."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <style>.x { Color: Red; }</style>
        <script>const FooBar = 1;</script>
        <p>Real prose here.</p>
        </body></html>
        """,
    )
    violations = _check(file)
    assert not any(
        "Color" in v["original"] or "FooBar" in v["original"] for v in violations
    ), f"Code content must not be linted, got: {violations}"


def test_h1_through_h6_all_linted(tmp_path):
    """Regression guard: the regex linter checked h1-h6; the parser must
    keep that coverage."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <h1>Bad Heading One</h1>
        <h6>Bad Heading Six</h6>
        </body></html>
        """,
    )
    originals = {v["original"] for v in _check(file)}
    assert "Bad Heading One" in originals
    assert "Bad Heading Six" in originals


def test_list_and_table_cell_linted(tmp_path):
    """The expanded element set covers list items and table cells, since
    those frequently hold short label-like prose in templates."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <ul><li>Item One</li></ul>
        <table><tr><th>Header One</th><td>Cell One</td></tr></table>
        </body></html>
        """,
    )
    originals = {v["original"] for v in _check(file)}
    assert "Item One" in originals
    assert "Header One" in originals
    assert "Cell One" in originals


def test_multi_sentence_paragraph_each_clause_validated(tmp_path):
    """A ``<p>`` containing multiple sentences is checked sentence-by-
    sentence so that "Forgot your password? Reset here" passes (each clause
    starts with a capital and is otherwise sentence case)."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <p>Forgot your password? Reset here</p>
        <p>Hello world. This is fine.</p>
        </body></html>
        """,
    )
    violations = _check(file)
    assert violations == [], f"Multi-sentence prose should pass, got: {violations}"


def test_numbered_markdown_heading_not_split_as_sentence(tmp_path):
    """Markdown headings like ``### 1. ssh to droplet`` must not be flagged:
    the leading ``1.`` is a numbering prefix, not a sentence end. This
    regression guards the multi-sentence detector from splitting on
    digit-period."""
    file = _write_md(
        tmp_path,
        """
        ### 1. ssh to droplet

        body
        """,
    )
    assert _check(file) == []


def test_unparseable_input_warns_and_returns_empty(tmp_path, capsys):
    """If selectolax cannot parse the document we skip it with a warning,
    not fall back to raw-text regex (the bug we just fixed)."""
    # selectolax is permissive; force the parser code path with a binary
    # blob in a .html file is hard. Instead, force the fail path by
    # patching the parser to raise.
    from scripts.dev import title_case_check as mod

    file = _write_html(tmp_path, "<p>Hello</p>")
    real = mod.HTMLParser

    class _BoomParser:
        def __init__(self, *_a, **_k):
            raise RuntimeError("simulated parse failure")

    mod.HTMLParser = _BoomParser
    try:
        violations = _check(file)
    finally:
        mod.HTMLParser = real
    captured = capsys.readouterr()
    assert violations == []
    assert "could not parse" in captured.err


def test_inline_title_case_ignore_marker_suppresses(tmp_path):
    """``{# title-case-ignore #}`` on the same line as a violation
    suppresses it. The escape hatch must keep working in parsed mode."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <h1>Some Bad Heading</h1>{# title-case-ignore #}
        </body></html>
        """,
    )
    assert _check(file) == []


def test_title_case_ignore_on_preceding_line_suppresses_in_html(tmp_path):
    """``{# title-case-ignore #}`` on the line *immediately above* the
    violation also suppresses it. This is the natural Jinja-comment
    placement and saves the agent from putting the marker inline; see
    #749 for the trial-and-error friction that drove this."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        {# title-case-ignore: brand name #}
        <h1>Bedlam Connect</h1>
        </body></html>
        """,
    )
    assert _check(file) == []


def test_title_case_ignore_on_preceding_line_suppresses_in_markdown(tmp_path):
    """Same preceding-line behaviour for Markdown headings — a
    ``<!-- title-case-ignore -->`` HTML comment above the heading
    suppresses it."""
    file = _write_md(
        tmp_path,
        """
        <!-- title-case-ignore: brand name -->
        # Bedlam Connect Is Here
        """,
    )
    assert _check(file) == []


def test_title_case_ignore_two_lines_above_does_not_suppress(tmp_path):
    """Only the *immediately* preceding line is consulted. A marker two
    lines above (with a content line in between) does not retroactively
    suppress an unrelated violation downstream — that would let a single
    stale marker silence unrelated lint."""
    file = _write_md(
        tmp_path,
        """
        <!-- title-case-ignore: this was for the line below -->
        # Sentence case heading
        # Another Bad Heading
        """,
    )
    violations = _check(file)
    assert len(violations) == 1
    assert "Another Bad Heading" in violations[0]["original"]


def test_titleignore_file_skips_whole_file(tmp_path):
    """A ``.titleignore`` listing a file pattern excludes that file even
    when it has clear violations."""
    file = _write_html(tmp_path, "<html><body><h1>Bad Heading</h1></body></html>")
    (tmp_path / ".titleignore").write_text("page.html\n", encoding="utf-8")
    assert _check(file) == []


def test_vendor_directory_is_skipped_entirely(tmp_path):
    """Vendored upstream trees (`vendor/<lib>/`) keep upstream's prose
    style; the directory walk must not descend into them."""
    vendored = tmp_path / "vendor" / "lib"
    vendored.mkdir(parents=True)
    (vendored / "README.md").write_text("# Installing Lib On Your App\n")
    ours = _write_md(tmp_path, "# Installing Lib On Your App")
    checker = TitleCaseChecker(fix_mode=False, respect_gitignore=False)
    violations = checker.check_directory(tmp_path)
    assert {Path(v["file"]).resolve() for v in violations} == {ours.resolve()}


def test_fix_mode_replaces_text_in_html(tmp_path):
    file = _write_html(tmp_path, "<html><body><h1>Bad Heading</h1></body></html>")
    checker = TitleCaseChecker(fix_mode=True, respect_gitignore=False)
    violations = checker.check_file(file)
    assert violations
    checker.fix_file(file, violations)
    assert "Bad heading" in file.read_text(encoding="utf-8")
    # Running again on the fixed file produces no violations.
    assert TitleCaseChecker(respect_gitignore=False).check_file(file) == []


# ---------------------------------------------------------------------------
# Vocabulary and code-span handling
#
# These are the rules that displaced the bulk of the project's
# ``title-case-ignore`` markers: the linter recognises domain acronyms and
# language names directly, and treats backtick-wrapped tokens in Markdown
# headers as code rather than prose. Each test pins a class of false
# positive that previously required a hand-placed ignore.
# ---------------------------------------------------------------------------


def test_markdown_header_starting_with_backtick_code_span(tmp_path):
    """A code span at the start of a header must not be lower-cased into
    prose (``\\`.env\\` vs \\`.env.test\\``` → ``.Env vs ...``).
    """
    file = _write_md(tmp_path, "### `.env` vs `.env.test`\n")
    assert _check(file) == []


def test_markdown_header_with_camelcase_in_backticks(tmp_path):
    """CamelCase identifiers wrapped in backticks must survive verbatim,
    not be lower-cased to ``baserepository``."""
    file = _write_md(tmp_path, "### CRUD primitives on `BaseRepository`\n")
    assert _check(file) == []


def test_acronyms_in_form_labels_pass(tmp_path):
    """Domain acronyms (ZIP/PII/DBT/EMDR) are part of the allowlist; form
    labels using them must not require per-line ignore markers."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <label>ZIP:</label>
        <label>Description (no PII):</label>
        <label>Treatment modality (optional, e.g. DBT, EMDR):</label>
        </body></html>
        """,
    )
    assert _check(file) == []


def test_language_names_in_prose_pass(tmp_path):
    """Language names (English, Spanish, ...) are part of the allowlist
    so labels like "Services in English?" don't need per-line ignores."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <label>Services preferred in language other than English?</label>
        <p>Available in Spanish and Mandarin.</p>
        </body></html>
        """,
    )
    assert _check(file) == []


def test_genuinely_miscased_acronym_neighbour_still_flags(tmp_path):
    """Adding ZIP to the allowlist must not let an adjacent miscased word
    slip through — only ZIP is preserved, the rest is sentence-cased."""
    file = _write_html(
        tmp_path,
        "<html><body><h1>ZIP Code Lookup</h1></body></html>",
    )
    originals = {v["original"] for v in _check(file)}
    assert "ZIP Code Lookup" in originals


def test_brand_phrase_bedlam_connect_passes_anywhere(tmp_path):
    """Multi-word brand phrases (``BRAND_PHRASES``) are preserved verbatim
    wherever they appear in prose — sentence-case lowercases every word
    after the first ("Bedlam Connect" → "Bedlam connect"), so a post-pass
    restores the canonical casing. Brand-name copy no longer needs
    per-line ``title-case-ignore`` markers (#728)."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <title>Bedlam Connect</title>
        <p>Sign in to your Bedlam Connect account.</p>
        <p>Bedlam Connect helps clinicians share openings.</p>
        </body></html>
        """,
    )
    assert _check(file) == []


def test_brand_mark_bedlam_alone_passes(tmp_path):
    """The standalone brand mark (``<span>Bedlam</span>``) lives in
    ``ALWAYS_CAPITALIZE`` so it stays capitalized in any position. The
    base template emits both forms inside a single ``<a>`` so the deep
    text is "Bedlam Connect Bedlam"; both halves must clear the linter."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <a href="/">
          <span>Bedlam Connect</span>
          <span>Bedlam</span>
        </a>
        </body></html>
        """,
    )
    assert _check(file) == []


def test_brand_phrase_does_not_creep_into_unrelated_prose(tmp_path):
    """The brand-phrase post-pass only restores casing when the phrase
    actually appears in the source — it must not over-capitalize random
    occurrences of either word."""
    file = _write_html(
        tmp_path,
        "<html><body><p>Connect with your peers.</p></body></html>",
    )
    # "Connect" alone is not a brand phrase and stays sentence-case
    # ("Connect with your peers." is already correct at position 0).
    assert _check(file) == []


def test_prose_text_skips_nested_lintable_subtrees(tmp_path):
    """A structural wrapper like ``<a><hgroup><h2>...</h2><p>...</p></hgroup></a>``
    must not be linted on its rolled-up deep text. ``<h2>`` and ``<p>`` are
    themselves linted units; including their text in the outer ``<a>``'s
    judgement creates the picker-pattern false positive that previously
    required ``<!-- title-case-ignore -->`` markers on every card."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <a href="/x">
          <hgroup>
            <h2>Solo practice</h2>
            <p>An individual clinician with availability.</p>
          </hgroup>
        </a>
        </body></html>
        """,
    )
    assert _check(file) == []


def test_prose_text_still_flags_inner_heading_violation(tmp_path):
    """The wrapper-skip must not hide real violations in nested lintable
    children — each child is judged on its own."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <a href="/x">
          <hgroup>
            <h2>Solo Practice</h2>
            <p>An individual clinician.</p>
          </hgroup>
        </a>
        </body></html>
        """,
    )
    originals = {v["original"] for v in _check(file)}
    assert "Solo Practice" in originals


def test_nested_li_dropdown_rollup_does_not_false_positive(tmp_path):
    """A dropdown nav (outer ``<li>`` wrapping ``<details>``/``<summary>``/
    inner ``<li><a>``) used to roll up to ``"Profile Sign out"`` on the
    outer ``<li>`` and require a ``title-case-ignore`` marker. The inner
    ``<a>`` tags are independent lintable units, so the outer wrapper
    should now be empty for lint purposes."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <ul>
          <li>
            <details>
              <summary aria-label="Profile menu">Profile</summary>
              <ul>
                <li><a href="/users/me">Profile</a></li>
                <li><a href="#" hx-post="/auth/sign-out">Sign out</a></li>
              </ul>
            </details>
          </li>
        </ul>
        </body></html>
        """,
    )
    assert _check(file) == []


def test_inline_emphasis_still_treated_as_one_prose_unit(tmp_path):
    """Non-lintable inline elements (``<em>``, ``<span>``) are still
    descended into so ``<p>Some <em>bad</em> text</p>`` is judged as one
    sentence — the wrapper-skip rule only fires on tags that are themselves
    lintable."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <p>Welcome to <em>the</em> service.</p>
        </body></html>
        """,
    )
    assert _check(file) == []


def test_aria_hook_value_breadcrumb_is_not_linted(tmp_path):
    """``aria-label="breadcrumb"`` is a reserved ARIA landmark hook, not
    prose — sentence-casing to ``"Breadcrumb"`` would defeat the screen
    reader convention."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <nav aria-label="breadcrumb"><a href="/x">Posts</a></nav>
        </body></html>
        """,
    )
    assert _check(file) == []


def test_aria_label_with_real_prose_still_linted(tmp_path):
    """The hook allowlist is narrow — generic ``aria-label`` values that
    aren't reserved landmark words remain prose."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <button aria-label="Close The Dialog">x</button>
        </body></html>
        """,
    )
    originals = {v["original"] for v in _check(file)}
    assert "Close The Dialog" in originals


def test_leading_symbol_yields_to_first_alpha_word(tmp_path):
    """A leading non-alphanumeric token (``«``, ``»``, bullet glyphs)
    doesn't have case and shouldn't consume the sentence-leading slot.
    The pagination macro emits ``« Prev`` / ``Next »`` — both should
    pass without per-line ignore markers."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <a href="/?page=1">&laquo; Prev</a>
        <a href="/?page=3">Next &raquo;</a>
        </body></html>
        """,
    )
    assert _check(file) == []


def test_leading_symbol_does_not_hide_miscased_first_word(tmp_path):
    """The symbol-yields rule still expects the first alpha word to start
    the sentence — ``« back to home`` is wrong and must be flagged."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <a href="/">&laquo; back to home</a>
        </body></html>
        """,
    )
    violations = _check(file)
    assert violations, "leading symbol must not silently capitalize the next word"


def test_numbered_prefix_still_consumes_first_slot(tmp_path):
    """A digit-led token like ``1.`` has a word character, so it does
    consume the first-word slot — preserving the existing
    ``1. ssh to droplet`` behaviour. This separates "no case at all"
    (symbols) from "case fixed by source" (numbers)."""
    file = _write_md(tmp_path, "### 1. ssh to droplet\n")
    assert _check(file) == []


def test_domain_acronyms_iop_npi_mcp_pass(tmp_path):
    """``IOP`` (intensive outpatient program), ``NPI`` (National Provider
    Identifier), and ``MCP`` (Model Context Protocol) appear in template
    prose and dev docs — promoting them to ``ALWAYS_CAPITALIZE`` replaces
    one-off ``title-case-ignore`` markers."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <p>For example a cohort, IOP, or day program.</p>
        <p>NPI 1234567890.</p>
        </body></html>
        """,
    )
    assert _check(file) == []

    md = _write_md(tmp_path, "### Playwright MCP for design review\n")
    assert _check(md) == []


def test_main_exits_with_error_when_selectolax_missing(monkeypatch, capsys):
    """If selectolax isn't importable, the CLI must hard-fail rather than
    silently skip every HTML/Jinja file. Regression for #198 — the old
    warn-and-skip behavior let `dev lint` pass locally with the wrong
    interpreter while CI (with deps installed) caught real violations."""
    from scripts.dev import title_case_check

    monkeypatch.setattr(title_case_check, "HTMLParser", None)
    monkeypatch.setattr("sys.argv", ["title_case_check.py", "--check-only"])

    rc = title_case_check.main()

    assert rc != 0
    err = capsys.readouterr().err
    assert "selectolax" in err
