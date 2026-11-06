#!/usr/bin/env python3
"""Lint headings/buttons/labels for sentence case across md/html/jinja."""

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Union

try:
    import pathspec
except ImportError:
    pathspec = None

try:
    from selectolax.parser import HTMLParser
except ImportError:
    HTMLParser = None


class TitleCaseChecker:
    """Check and optionally fix title case violations."""

    # Markdown-only patterns. HTML/Jinja are handled by the parsed-mode
    # checker, not by these regexes.
    PATTERNS = {
        "markdown": [
            (r"^(#{1,6})\s+(.+)$", "markdown_header"),
            (r"<h([1-6]).*?>(.*?)</h\1>", "html_header_in_md"),
        ],
    }

    # Element names whose text content is treated as user-facing prose and
    # linted for sentence case. Anything not in this set is structurally
    # ignored — its text isn't prose by default.
    LINTABLE_TEXT_TAGS = {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "a",
        "button",
        "label",
        "title",
        "strong",
        "b",
        "li",
        "td",
        "th",
        "summary",
        "figcaption",
        "dt",
        "dd",
    }

    # Attribute names whose *values* are user-facing prose. Every other
    # attribute value (href, src, class, id, style, data-*, hx-*, ...) is
    # ignored — it isn't prose, no matter what it looks like.
    LINTABLE_ATTR_NAMES = {
        "title",
        "alt",
        "placeholder",
        "aria-label",
        "aria-description",
    }

    # Elements whose entire subtree is non-prose by definition (code, raw
    # CSS/JS). The walker never descends into these.
    NEVER_DESCEND_TAGS = {"script", "style", "code", "pre", "kbd"}

    # Reserved ARIA landmark/role hook values — document-structure
    # vocabulary, not user-facing prose. They appear in ``aria-label`` so
    # assistive tech announces a familiar region name; sentence-casing
    # them ("Breadcrumb") would defeat the hook.
    ARIA_HOOK_VALUES = {
        "breadcrumb",
        "pagination",
    }

    FILE_EXTENSIONS = {
        ".md": "markdown",
        ".markdown": "markdown",
        ".html": "html",
        ".htm": "html",
        ".jinja": "jinja",
        ".jinja2": "jinja",
    }

    # Binary extensions silently skipped — never readable as text.
    BINARY_EXTENSIONS = {
        ".db",
        ".sqlite",
        ".sqlite3",
    }

    # Words that should remain capitalized (proper nouns, acronyms, etc.).
    # Add domain acronyms and language names here rather than asking authors
    # to scatter ``title-case-ignore`` markers — the marker is the escape
    # hatch for one-offs, not a vocabulary problem.
    ALWAYS_CAPITALIZE = {
        # Web/protocol acronyms
        "API",
        "APIs",
        "URL",
        "URLs",
        "HTTP",
        "HTTPS",
        "JSON",
        "XML",
        "HTML",
        "CSS",
        "JS",
        "SQL",
        "REST",
        "RESTful",
        "OAuth",
        "JWT",
        "UUID",
        "UUIDs",
        # Tech / framework names
        "FastAPI",
        "SQLAlchemy",
        "APScheduler",
        "Jinja2",
        "pytest",
        "GitHub",
        "PostgreSQL",
        "SQLite",
        "Docker",
        "Python",
        "JavaScript",
        "TypeScript",
        "Pact",  # Contract testing framework
        # General-domain acronyms
        "CRUD",
        "TDD",
        "LLM",
        "LLMs",
        "AI",
        "MVP",
        "PR",
        "PRs",
        "API",
        "APIs",
        "URL",
        "URLs",
        "ID",
        "IDs",
        "UUID",
        "UUIDs",
        # App-domain acronyms (intake forms, public-facing copy)
        "ZIP",  # Postal code field
        "PII",  # Personally identifiable information
        "DBT",  # Dialectical behavior therapy
        "EMDR",  # Eye movement desensitization and reprocessing
        "IOP",  # Intensive outpatient program
        "NPI",  # National Provider Identifier
        "LCSW",  # Licensed Clinical Social Worker
        "LMFT",  # Licensed Marriage and Family Therapist
        "LPC",  # Licensed Professional Counselor
        "LMHC",  # Licensed Mental Health Counselor
        "MCP",  # Model Context Protocol (referenced in dev docs)
        # UI libraries
        "Lucide",  # icon library used throughout the app
        # Brand mark — the short form rendered on narrow viewports.
        # Multi-word brand phrases (e.g. "Bedlam Connect") live in
        # ``BRAND_PHRASES`` below; this entry covers the standalone
        # ``<span class="brand-mark">Bedlam</span>`` shape.
        "Bedlam",
        # Language names — surface in form labels ("non-English", "Spanish")
        # and standard sentence-case rules would lowercase them.
        "English",
        "Spanish",
        "Mandarin",
        "Cantonese",
        "French",
        "German",
        "Japanese",
        "Korean",
        "Vietnamese",
        "Tagalog",
        "Arabic",
        "Hebrew",
        "Hindi",
        "Russian",
        "Italian",
        "Portuguese",
    }

    # Multi-word brand phrases preserved verbatim (case-sensitive) when
    # they appear in source. Sentence-case conversion would lowercase the
    # second word ("Bedlam Connect" → "Bedlam connect"); the post-pass
    # in ``_convert_single_sentence`` restores the canonical casing. The
    # single-word brand mark ("Bedlam") lives in ``ALWAYS_CAPITALIZE``.
    BRAND_PHRASES = {
        "Bedlam Connect",
    }

    # HTTP methods are ambiguous: they overlap with common English words
    # ("post", "get", "put", "delete", "head", "options", "patch", "trace",
    # "connect"). Treating them like ALWAYS_CAPITALIZE causes false positives
    # in template prose ("New post" → "New POST"). We preserve uppercase when
    # the source already wrote it that way (e.g. docs: "POST /users") but
    # leave lowercase occurrences alone to be normalized as ordinary words.
    HTTP_METHODS = {
        "POST",
        "GET",
        "PUT",
        "DELETE",
        "PATCH",
        "HEAD",
        "OPTIONS",
        "TRACE",
        "CONNECT",
    }

    # Exception patterns (regex patterns to ignore)
    IGNORE_PATTERNS = [
        r"title-case-ignore",  # Comment containing this phrase
        r"<!-- title-case-ignore -->",  # HTML comment
        r"{# title-case-ignore #}",  # Jinja comment
        r"# title-case-ignore",  # Markdown comment
    ]

    # Jinja preprocessing: strip Jinja syntax before handing source to the
    # HTML parser. Comments drop entirely; statements and expressions are
    # replaced with an opaque sentinel so the parser still sees syntactically
    # valid HTML (e.g. ``href="{{ url }}"`` → ``href="…SENTINEL…"``) and so
    # text-node boundaries are preserved. Any prose text or attribute value
    # whose final form *contains* the sentinel is skipped by the linter —
    # there's a runtime substitution there and we can't judge its case.
    JINJA_SENTINEL = "JINJAPLACEHOLDER"
    JINJA_REGEXES = [
        (re.compile(r"{#.*?#}", re.DOTALL), ""),
        (re.compile(r"{%.*?%}", re.DOTALL), JINJA_SENTINEL),
        (re.compile(r"{{.*?}}", re.DOTALL), JINJA_SENTINEL),
    ]

    def __init__(self, fix_mode: bool = False, respect_gitignore: bool = True):
        self.fix_mode = fix_mode
        self.respect_gitignore = respect_gitignore
        self.violations: List[Dict] = []
        self.gitignore_spec = None
        self.git_root = None

        if self.respect_gitignore:
            self._load_gitignore()

    def _find_git_root(self, start_path: Path = None) -> Path:
        """Find the root of the git repository."""
        if start_path is None:
            start_path = Path.cwd()

        current = start_path.resolve()
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent

        # If no .git found, return the starting directory
        return start_path.resolve()

    def _load_gitignore(self):
        """Load gitignore patterns from .gitignore file."""
        if pathspec is None:
            print(
                "Warning: pathspec library not available. Install with: pip install pathspec",
                file=sys.stderr,
            )
            print("Continuing without gitignore support...", file=sys.stderr)
            return

        self.git_root = self._find_git_root()
        gitignore_path = self.git_root / ".gitignore"

        if not gitignore_path.exists():
            return

        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                gitignore_content = f.read()

            self.gitignore_spec = pathspec.PathSpec.from_lines(
                "gitwildmatch", gitignore_content.splitlines()
            )
        except Exception as e:
            print(f"Warning: Could not load .gitignore: {e}", file=sys.stderr)

    def _is_gitignored(self, file_path: Path) -> bool:
        """Check if a file is ignored by gitignore."""
        if (
            not self.respect_gitignore
            or self.gitignore_spec is None
            or self.git_root is None
        ):
            return False

        try:
            # Get relative path from git root
            relative_path = file_path.resolve().relative_to(self.git_root)
            return self.gitignore_spec.match_file(str(relative_path))
        except (ValueError, OSError):
            # File is outside git repository or other error
            return False

    def should_ignore_line(self, line: str) -> bool:
        """Check if a line should be ignored based on exception patterns."""
        for pattern in self.IGNORE_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                return True
        return False

    def is_violation_suppressed(
        self, content: str, line_num: int, lines: Optional[List[str]] = None
    ) -> bool:
        """Return True if line `line_num` (1-indexed) or its immediately
        preceding line carries an ignore marker.

        The preceding-line check is the lint equivalent of
        `# eslint-disable-next-line` — it lets templates put the marker on
        its own line so brand-name copy reads cleanly:

            {# title-case-ignore: brand name #}
            <h2>Bedlam Connect</h2>

        Only the *immediately* preceding line is consulted (no blank-line
        skipping) so a far-away comment can never attribute itself to an
        unrelated violation. See #749 for the motivating friction."""
        if lines is None:
            lines = content.split("\n")
        if 1 <= line_num <= len(lines) and self.should_ignore_line(lines[line_num - 1]):
            return True
        if line_num >= 2 and self.should_ignore_line(lines[line_num - 2]):
            return True
        return False

    def should_ignore_file(self, file_path: Path) -> bool:
        """Check if entire file should be ignored based on .titleignore file or gitignore."""
        # Skip known binary extensions silently — these are never text content
        # we'd want to title-case-check, and reading them produces utf-8 noise.
        if file_path.suffix.lower() in self.BINARY_EXTENSIONS:
            return True

        # Skip anything under a top-level data/ directory — these are runtime
        # artifacts (sqlite DBs, fixtures), not source files.
        try:
            parts = file_path.resolve().parts
        except OSError:
            parts = file_path.parts
        if "data" in parts:
            return True

        # Check gitignore first
        if self._is_gitignored(file_path):
            return True

        # Check .titleignore file
        ignore_file = file_path.parent / ".titleignore"
        if ignore_file.exists():
            patterns = ignore_file.read_text().strip().split("\n")
            for pattern in patterns:
                pattern = pattern.strip()
                if pattern and not pattern.startswith("#"):
                    if file_path.match(pattern) or str(file_path).endswith(pattern):
                        return True
        return False

    def is_colon_pattern(self, text: str) -> bool:
        """Exempt "Chapter 1: Foo", "Step 1: Foo", and titles with ≥3 words after the separator."""
        clean_text = re.sub(r"<[^>]+>", "", text).strip()

        for separator in [":", " - "]:
            if separator in clean_text:
                parts = clean_text.split(separator, 1)
                if len(parts) == 2:
                    before_sep = parts[0].strip()
                    after_sep = parts[1].strip()

                    if before_sep and after_sep:
                        after_words = after_sep.split()
                        if len(after_words) >= 3:
                            return True

                        if re.match(
                            r"^(Chapter|Section|Part|Book)\s+\d+$",
                            before_sep,
                            re.IGNORECASE,
                        ):
                            return True

                        if re.match(r"^Step\s+\d+$", before_sep, re.IGNORECASE):
                            return True

        return False

    def remove_leading_emojis(self, text: str) -> str:
        emoji_pattern = r"^[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002600-\U000027BF\U0001F900-\U0001F9FF\U0001F018-\U0001F270\U0001F000-\U0001F02F\U0001F0A0-\U0001F0FF\U0001F100-\U0001F64F\U0001F170-\U0001F251\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000027BF\U0001F018-\U0001F270\U0001F000-\U0001F02F\U0001F0A0-\U0001F0FF\U0001F100-\U0001F64F\U0001F170-\U0001F251]+\s*"

        cleaned = re.sub(emoji_pattern, "", text)
        return cleaned

    def convert_to_sentence_case(self, text: str) -> str:
        """Sentence-case each clause, preserving proper nouns and acronyms."""
        if self.is_colon_pattern(text):
            return text

        # Split only when a letter precedes the punctuation (so "1. foo"
        # doesn't split on a numbering) AND an uppercase letter follows the
        # whitespace (so "vs. divergence" or "complete! all" don't split).
        parts = re.split(r"(?<=[a-zA-Z][.!?])\s+(?=[A-Z])", text.strip())
        if len(parts) > 1:
            return " ".join(self._convert_single_sentence(p) for p in parts)

        return self._convert_single_sentence(text)

    def _convert_single_sentence(self, text: str) -> str:
        clean_text = re.sub(r"<[^>]+>", "", text).strip()

        if not clean_text:
            return text

        original_clean = clean_text
        clean_text_no_emoji = self.remove_leading_emojis(clean_text)
        emoji_prefix = original_clean[: len(original_clean) - len(clean_text_no_emoji)]

        capitalize_map = {word.upper(): word for word in self.ALWAYS_CAPITALIZE}

        words = clean_text_no_emoji.split()
        if not words:
            return text

        # Pure-symbol prefixes (``«``, ``»``, bullets) don't have case and
        # shouldn't consume the sentence-leading slot — the first *word with
        # alphanumeric content* is what the sentence starts on. A digit-led
        # token like ``1.`` does have a word character and does consume the
        # slot, preserving the existing "1. ssh to droplet" behaviour.
        sentence_started = False
        result_words = []
        for word in words:
            # Backtick-wrapped code spans (`.env`, `BaseRepository`) are
            # identifiers, not prose — preserve verbatim, including for the
            # first-word rule that would otherwise mangle "`.env` vs `.env.test`".
            if "`" in word:
                result_words.append(word)
                if re.search(r"\w", word):
                    sentence_started = True
                continue

            clean_word = re.sub(r"[^\w]", "", word)

            # HTTP methods: preserve when source is uppercase (doc style),
            # otherwise treat as a regular English word.
            is_http_method = clean_word.upper() in self.HTTP_METHODS
            if is_http_method and clean_word.isupper():
                result_words.append(word)
                if clean_word:
                    sentence_started = True
                continue

            if not sentence_started and clean_word:
                if not is_http_method and clean_word.upper() in capitalize_map:
                    proper_case = capitalize_map[clean_word.upper()]
                    result_words.append(word.replace(clean_word, proper_case))
                else:
                    new_word = word.replace(
                        clean_word, clean_word[0].upper() + clean_word[1:].lower()
                    )
                    result_words.append(new_word)
                sentence_started = True
            else:
                if not is_http_method and clean_word.upper() in capitalize_map:
                    proper_case = capitalize_map[clean_word.upper()]
                    result_words.append(word.replace(clean_word, proper_case))
                elif clean_word:
                    result_words.append(word.replace(clean_word, clean_word.lower()))
                else:
                    result_words.append(word)

        sentence_case = emoji_prefix + " ".join(result_words)

        # Restore multi-word brand phrases. Sentence-case lowercases every
        # word after the first ("Bedlam Connect" → "Bedlam connect");
        # this pass swaps any case-insensitive match back to the canonical
        # form so brand-name copy doesn't need per-line `title-case-ignore`
        # markers (#728).
        for brand in self.BRAND_PHRASES:
            if re.search(re.escape(brand), original_clean, re.IGNORECASE):
                sentence_case = re.sub(
                    re.escape(brand), brand, sentence_case, flags=re.IGNORECASE
                )

        if "<" in text and ">" in text:
            return text.replace(original_clean, sentence_case)

        return sentence_case

    def is_sentence_case(self, text: str) -> bool:
        """Check if text follows sentence case rules."""
        expected = self.convert_to_sentence_case(text)
        return text == expected

    def _detect_jinja_syntax(self, content: str) -> bool:
        """Detect if content contains Jinja template syntax."""
        jinja_patterns = [
            r"{%.*?%}",  # Jinja blocks like {% block %}, {% for %}, etc.
            r"{{.*?}}",  # Jinja variables like {{ variable }}
            r"{#.*?#}",  # Jinja comments like {# comment #}
        ]

        for pattern in jinja_patterns:
            if re.search(pattern, content, re.DOTALL):
                return True
        return False

    def _get_file_type(self, file_path: Path, content: str = None) -> str:
        """Determine the file type, with special handling for HTML files that contain Jinja syntax."""
        extension = file_path.suffix.lower()
        if extension not in self.FILE_EXTENSIONS:
            return None

        base_type = self.FILE_EXTENSIONS[extension]

        # If it's an HTML file, check if it contains Jinja syntax
        if base_type == "html":
            if content is None:
                try:
                    content = file_path.read_text(encoding="utf-8")
                except Exception:
                    return base_type

            if (
                self._detect_jinja_syntax(content)
                or "template" in str(file_path).lower()
            ):
                return "jinja"

        return base_type

    def check_file(self, file_path: Path) -> List[Dict]:
        """Check a single file for title case violations."""
        if self.should_ignore_file(file_path):
            return []

        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # Binary or unreadable file — silently skip, no diagnostic noise.
            return []

        file_type = self._get_file_type(file_path, content)
        if file_type is None:
            return []

        if file_type in ("html", "jinja"):
            return self._check_html_parsed(content, file_path)
        return self._check_markdown(content, file_path)

    def _check_markdown(self, content: str, file_path: Path) -> List[Dict]:
        """Line-based regex check for Markdown files."""
        patterns = self.PATTERNS["markdown"]
        violations: List[Dict] = []

        lines = content.split("\n")
        in_fenced_code_block = False

        for line_num, line in enumerate(lines, 1):
            # Track Markdown fenced code blocks (``` or ~~~). Anything inside
            # them is source code, not prose — `#` and `<h1>` patterns there
            # are syntax, not headings, and must not be flagged.
            stripped = line.lstrip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fenced_code_block = not in_fenced_code_block
                continue

            if in_fenced_code_block:
                continue

            if self.is_violation_suppressed(content, line_num, lines):
                continue

            for pattern, pattern_type in patterns:
                matches = re.finditer(pattern, line, re.IGNORECASE | re.DOTALL)
                for match in matches:
                    if pattern_type == "markdown_header":
                        title_text = match.group(2).strip()
                        header_level = match.group(1)
                    elif pattern_type == "html_header_in_md":
                        title_text = match.group(2).strip()
                        header_level = f"h{match.group(1)}"
                    elif pattern_type == "standalone_label":
                        title_text = match.group(1).strip()
                        header_level = "label"
                    else:
                        continue

                    if title_text and not self.is_sentence_case(title_text):
                        violations.append(
                            {
                                "file": file_path,
                                "line": line_num,
                                "original": title_text,
                                "suggested": self.convert_to_sentence_case(title_text),
                                "pattern_type": pattern_type,
                                "header_level": header_level,
                                "full_line": line,
                            }
                        )

        return violations

    def _strip_jinja(self, content: str) -> str:
        """Strip Jinja syntax so the HTML parser doesn't choke on it.

        Statements and comments drop entirely. Expressions are replaced with
        an opaque alphabetic token so attributes that embed them
        (``href="{{ url }}"``) remain syntactically valid HTML and so
        surrounding text-node boundaries are preserved.
        """
        for pattern, replacement in self.JINJA_REGEXES:
            content = pattern.sub(replacement, content)
        return content

    def _check_html_parsed(self, content: str, file_path: Path) -> List[Dict]:
        """Parse HTML/Jinja and lint only prose nodes (text in content
        elements + a small allowlist of user-facing attribute values).

        This is the systemic fix for what the regex-mode linter couldn't
        express: structural distinction between text nodes and attribute
        values. Inline ``style="..."`` is invisible here because ``style``
        isn't in ``LINTABLE_ATTR_NAMES``; ``<script>``/``<style>`` subtrees
        are skipped by ``NEVER_DESCEND_TAGS``.

        Callers must ensure ``selectolax`` is importable before invoking
        this — the CLI guards in ``main()``. Per-file warn-and-skip used
        to live here and silently masked missing-dep environments
        (regression #198).
        """
        stripped_content = self._strip_jinja(content)

        try:
            tree = HTMLParser(stripped_content)
        except Exception as e:
            # Parser failure is a "skip with warning", never "fall back to
            # raw-text regex" — that's the bug we just fixed.
            print(
                f"Warning: could not parse {file_path}: {e}; skipping",
                file=sys.stderr,
            )
            return []

        if tree.root is None:
            return []

        violations: List[Dict] = []
        line_starts = self._compute_line_starts(content)
        self._walk(tree.root, file_path, content, line_starts, violations)
        return violations

    @staticmethod
    def _compute_line_starts(content: str) -> List[int]:
        """Return the character offset at which each line starts."""
        starts = [0]
        for i, ch in enumerate(content):
            if ch == "\n":
                starts.append(i + 1)
        return starts

    @staticmethod
    def _offset_to_line(offset: int, line_starts: List[int]) -> int:
        """Map a 0-based character offset back to a 1-based line number."""
        # Binary search would be faster; linear is plenty for source files.
        line = 1
        for i, start in enumerate(line_starts):
            if start > offset:
                break
            line = i + 1
        return line

    def _locate_in_source(
        self,
        needles: List[str],
        content: str,
        line_starts: List[int],
    ) -> int:
        """Return the 1-based line number of the first needle that occurs
        verbatim in ``content``. Falls back to line 1.

        Callers pass several candidate strings ordered from most to least
        specific (e.g. the joined deep text, then the first leaf text-node).
        Inline children — ``<code>``, ``<em>``, etc. — break verbatim
        searches on the deep text but the leaf-fragment search still finds a
        plausible line for diagnostics and ``title-case-ignore`` placement.
        """
        for needle in needles:
            if not needle:
                continue
            idx = content.find(needle)
            if idx != -1:
                return self._offset_to_line(idx, line_starts)
        return 1

    def _walk(
        self,
        node,
        file_path: Path,
        content: str,
        line_starts: List[int],
        violations: List[Dict],
    ) -> None:
        """Recursively walk the parsed tree and collect violations."""
        tag = node.tag

        if tag in self.NEVER_DESCEND_TAGS:
            return

        # Lint attribute values from the user-facing allowlist.
        if node.attributes:
            for attr_name, attr_value in node.attributes.items():
                if attr_name not in self.LINTABLE_ATTR_NAMES:
                    continue
                if not attr_value:
                    continue
                if (
                    attr_name in ("aria-label", "aria-description")
                    and attr_value.strip().lower() in self.ARIA_HOOK_VALUES
                ):
                    # Reserved ARIA landmark hook (e.g. ``aria-label="breadcrumb"``)
                    # — not prose.
                    continue
                self._maybe_record(
                    text=attr_value,
                    header_level=f"@{attr_name}",
                    file_path=file_path,
                    content=content,
                    line_starts=line_starts,
                    violations=violations,
                    locator_candidates=[attr_value],
                )

        # Lint the prose text of recognised content elements. ``_prose_text``
        # treats other ``LINTABLE_TEXT_TAGS`` as boundaries — those subtrees
        # are linted as independent units when the walker reaches them, so
        # including their text in the outer rollup double-counts and creates
        # false positives (e.g. ``<a><hgroup><h2>X</h2><p>Y</p></hgroup></a>``
        # used to flag the joined ``"X Y"`` even when X and Y were each
        # correct in isolation).
        if tag in self.LINTABLE_TEXT_TAGS:
            prose = self._prose_text(node)
            if prose:
                normalized = " ".join(prose.split())
                if normalized:
                    locator_candidates = [normalized, prose]
                    leaf = self._first_leaf_text(node)
                    if leaf:
                        locator_candidates.append(leaf)
                    self._maybe_record(
                        text=normalized,
                        header_level=tag,
                        file_path=file_path,
                        content=content,
                        line_starts=line_starts,
                        violations=violations,
                        locator_candidates=locator_candidates,
                    )

        # Descend.
        for child in node.iter(include_text=False):
            self._walk(child, file_path, content, line_starts, violations)

    def _prose_text(self, node) -> str:
        """Concatenated text inside ``node``, stopping at any nested element
        that's itself in ``LINTABLE_TEXT_TAGS``.

        Those subtrees are linted as independent prose units when the walker
        reaches them; including their text in the outer rollup creates
        false positives on structural wrappers like
        ``<a><hgroup><h2>...</h2><p>...</p></hgroup></a>``. Inline emphasis
        elements that aren't lintable (e.g. ``<em>``, ``<span>``) are still
        descended into so ``<p>Some <em>bad</em> text</p>`` is judged as
        one prose unit.
        """
        fragments: List[str] = []
        for child in node.iter(include_text=True):
            if child.tag == "-text":
                fragments.append(child.text() or "")
            elif child.tag in self.NEVER_DESCEND_TAGS:
                continue
            elif child.tag in self.LINTABLE_TEXT_TAGS:
                continue
            else:
                inner = self._prose_text(child)
                if inner:
                    fragments.append(inner)
        return "".join(fragments)

    def _first_leaf_text(self, node) -> str:
        """Return the first non-empty text-node descendant's content.

        Used as a locator fallback: when an element's deep text doesn't
        appear verbatim in source (because inline children like ``<code>``
        broke the substring), the first leaf text *is* a verbatim source
        substring and gives us a reliable line number for diagnostics.
        """
        for child in node.iter(include_text=True):
            if child.tag == "-text":
                fragment = (child.text() or "").strip()
                if fragment:
                    return fragment
            else:
                if child.tag in self.NEVER_DESCEND_TAGS:
                    continue
                inner = self._first_leaf_text(child)
                if inner:
                    return inner
        return ""

    def _maybe_record(
        self,
        text: str,
        header_level: str,
        file_path: Path,
        content: str,
        line_starts: List[int],
        violations: List[Dict],
        locator_candidates: List[str],
    ) -> None:
        """If ``text`` violates sentence case, append a violation record."""
        text = text.strip()
        if not text:
            return
        if self.JINJA_SENTINEL in text:
            # Text contains a Jinja substitution (`{{ ... }}` or `{% ... %}`).
            # We can't judge the rendered case, so skip.
            return
        if self.is_sentence_case(text):
            return

        line_num = self._locate_in_source(locator_candidates, content, line_starts)

        # Honour the per-line escape hatch even in parsed mode: if the
        # source line — or the immediately preceding line, see #749 —
        # carries a ``title-case-ignore`` marker, suppress.
        try:
            line_text = content.split("\n")[line_num - 1]
        except IndexError:
            line_text = ""
        if self.is_violation_suppressed(content, line_num):
            return

        violations.append(
            {
                "file": file_path,
                "line": line_num,
                "original": text,
                "suggested": self.convert_to_sentence_case(text),
                "pattern_type": "html_parsed",
                "header_level": header_level,
                "full_line": line_text,
            }
        )

    def fix_file(self, file_path: Path, violations: List[Dict]) -> bool:
        """Fix title case violations in a file."""
        if not violations:
            return False

        try:
            content = file_path.read_text(encoding="utf-8")

            # Sort violations by line number in reverse order to maintain line positions
            sorted_violations = sorted(
                violations, key=lambda v: v["line"], reverse=True
            )

            lines = content.split("\n")
            for violation in sorted_violations:
                line_idx = violation["line"] - 1
                if 0 <= line_idx < len(lines):
                    lines[line_idx] = lines[line_idx].replace(
                        violation["original"], violation["suggested"]
                    )

            file_path.write_text("\n".join(lines), encoding="utf-8")
            return True

        except Exception as e:
            print(f"Error fixing {file_path}: {e}", file=sys.stderr)
            return False

    def check_directory(self, directory: Path, recursive: bool = True) -> List[Dict]:
        """Check all files in a directory, skipping hidden directories."""
        all_violations = []

        def should_skip_directory(dir_path: Path) -> bool:
            """Check if a directory should be skipped entirely."""
            # Skip hidden directories (starting with '.')
            if dir_path.name.startswith("."):
                return True

            # Skip common build/cache directories
            skip_dirs = {
                "__pycache__",
                "node_modules",
                ".pytest_cache",
                ".mypy_cache",
                ".tox",
                "venv",
                ".venv",
                "env",
                ".env",
                "build",
                "dist",
                ".coverage",
                # Vendored upstream trees keep upstream's prose style —
                # see vendor/README.md.
                "vendor",
            }
            if dir_path.name in skip_dirs:
                return True

            return False

        def scan_directory(current_dir: Path, is_recursive: bool = True):
            """Recursively scan directory, skipping hidden directories."""
            try:
                for item in current_dir.iterdir():
                    if item.is_file():
                        if not self.should_ignore_file(item):
                            violations = self.check_file(item)
                            all_violations.extend(violations)
                    elif item.is_dir() and is_recursive:
                        # Skip hidden and unwanted directories
                        if not should_skip_directory(item):
                            scan_directory(item, is_recursive)
            except PermissionError:
                # Skip directories we don't have permission to read
                pass
            except Exception as e:
                print(f"Warning: Error scanning {current_dir}: {e}", file=sys.stderr)

        scan_directory(directory, recursive)
        return all_violations

    def run(self, paths: List[Union[str, Path]]) -> int:
        """Run the checker on the given paths."""
        all_violations = []

        for path_str in paths:
            path = Path(path_str)
            if path.is_file():
                violations = self.check_file(path)
                all_violations.extend(violations)
            elif path.is_dir():
                violations = self.check_directory(path)
                all_violations.extend(violations)
            else:
                print(f"Warning: {path} does not exist", file=sys.stderr)

        if not all_violations:
            print("✅ No title case violations found!")
            return 0

        # Group violations by file
        by_file = {}
        for violation in all_violations:
            file_path = violation["file"]
            if file_path not in by_file:
                by_file[file_path] = []
            by_file[file_path].append(violation)

        # Report violations
        total_violations = len(all_violations)
        print(
            f"❌ Found {total_violations} title case violation(s) in {len(by_file)} file(s):"
        )
        print()

        for file_path, violations in by_file.items():
            print(f"📄 {file_path}")
            for violation in violations:
                print(f"  Line {violation['line']:3d}: {violation['header_level']}")
                print(f"    Current:   '{violation['original']}'")
                print(f"    Suggested: '{violation['suggested']}'")
                print()

        if self.fix_mode:
            print("🔧 Fixing violations...")
            fixed_count = 0
            for file_path, violations in by_file.items():
                if self.fix_file(file_path, violations):
                    fixed_count += len(violations)
                    print(f"✅ Fixed {len(violations)} violation(s) in {file_path}")

            print(f"\n✅ Fixed {fixed_count} out of {total_violations} violations")
            return 0 if fixed_count == total_violations else 1
        else:
            print("💡 Run with --fix to automatically correct these violations")
            print(
                "💡 Add 'title-case-ignore' on the violating line OR the line "
                "immediately above it"
            )
            print("💡 Create .titleignore file to ignore specific files/patterns")
            return 1


def main():
    parser = argparse.ArgumentParser(
        description="Check and fix title case violations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
      python scripts/dev/title_case_check.py                    # Check all files
    python scripts/dev/title_case_check.py --fix              # Auto-fix violations
    python scripts/dev/title_case_check.py templates/         # Check specific directory
    python scripts/dev/title_case_check.py README.md src/     # Check specific files/dirs

Exception handling:
  - Add 'title-case-ignore' in a comment on the violating line OR the
    line immediately above it (e.g. `{# title-case-ignore: brand #}`
    on its own line above an `<h2>` works the same as `<h2>...</h2>
    {# title-case-ignore #}` inline).
  - Create .titleignore file with glob patterns to ignore files
  - Use --check-only to report without fixing
  - Use --no-gitignore to disable automatic gitignore support
        """,
    )

    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to check (default: current directory)",
    )

    parser.add_argument(
        "--fix", action="store_true", help="Automatically fix title case violations"
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check for violations, do not fix",
    )

    parser.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Disable automatic gitignore support (check all files)",
    )

    args = parser.parse_args()

    if HTMLParser is None:
        # Hard-fail rather than warn-and-skip per file: warn-and-skip
        # used to mean every HTML/Jinja template silently skipped, so a
        # real violation could pass `dev lint` locally and only surface
        # in CI.
        print(
            "Error: selectolax is not installed in this interpreter "
            f"({sys.executable}). HTML/Jinja templates cannot be checked. "
            "Install with: pip install selectolax",
            file=sys.stderr,
        )
        return 1

    # --check-only overrides --fix
    fix_mode = args.fix and not args.check_only
    respect_gitignore = not args.no_gitignore

    checker = TitleCaseChecker(fix_mode=fix_mode, respect_gitignore=respect_gitignore)
    return checker.run(args.paths)


if __name__ == "__main__":
    sys.exit(main())
