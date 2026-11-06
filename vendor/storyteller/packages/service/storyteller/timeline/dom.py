"""
Minimal DOM mirror for rrweb recordings.

Builds a node map from full snapshots (event type 2) and applies mutation
events (type 3, source 0). Enough to resolve any node id to its tag,
attributes, text and ancestors, and to notice when things appear or change.
No layout, no CSS cascade: visibility is inferred from inline style and
class-name conventions, which covers most sites well enough for a timeline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator

NODE_DOCUMENT, NODE_DOCTYPE, NODE_ELEMENT, NODE_TEXT, NODE_CDATA, NODE_COMMENT = range(6)

INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "summary", "option", "label"}
INTERACTIVE_ROLES = {"button", "link", "tab", "menuitem", "checkbox", "radio", "switch", "option", "combobox", "textbox", "slider"}

_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
_SHOWN_CLASS = re.compile(r"\b(show|shown|visible|open|opened|active|is-visible|is-open|is-active)\b", re.I)


@dataclass
class Node:
    id: int
    type: int
    tag: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
    text: str | None = None
    parent: int | None = None
    children: list[int] = field(default_factory=list)
    is_shadow_host: bool = False


class DOM:
    def __init__(self) -> None:
        self.nodes: dict[int, Node] = {}

    # ---- building -------------------------------------------------------
    def load_snapshot(self, root: dict[str, Any]) -> None:
        self.nodes = {}
        self._add_tree(root, None)

    def _add_tree(self, raw: dict[str, Any], parent: int | None) -> None:
        n = Node(
            id=raw["id"],
            type=raw["type"],
            tag=(raw.get("tagName") or "").lower() or None,
            attrs=dict(raw.get("attributes") or {}),
            text=raw.get("textContent"),
            parent=parent,
            is_shadow_host=bool(raw.get("isShadowHost")),
        )
        self.nodes[n.id] = n
        if parent is not None and parent in self.nodes:
            self.nodes[parent].children.append(n.id)
        for child in raw.get("childNodes") or []:
            self._add_tree(child, n.id)

    def apply_mutation(self, data: dict[str, Any]) -> "MutationResult":
        res = MutationResult()
        for rem in data.get("removes") or []:
            nid = rem.get("id")
            if nid in self.nodes:
                n = self.nodes[nid]
                if n.type == NODE_TEXT and n.parent is not None:
                    res.removed_text.setdefault(n.parent, []).append(n.text or "")
                else:
                    res.removed.append(self.snapshot_info(nid))
                self._remove(nid)
        for add in data.get("adds") or []:
            node = add.get("node") or {}
            parent = add.get("parentId")
            self._add_tree(node, parent)
            if parent in self.nodes and node.get("id") not in self.nodes[parent].children:
                self.nodes[parent].children.append(node["id"])
            res.added.append(node.get("id"))
        for t in data.get("texts") or []:
            n = self.nodes.get(t.get("id"))
            if n is not None:
                old = n.text
                n.text = t.get("value")
                res.text_changed.append((n.id, old, n.text))
        for a in data.get("attributes") or []:
            n = self.nodes.get(a.get("id"))
            if n is None:
                continue
            changes = a.get("attributes") or {}
            before = {k: n.attrs.get(k) for k in changes}
            for k, v in changes.items():
                if v is None:
                    n.attrs.pop(k, None)
                else:
                    n.attrs[k] = v
            res.attr_changed.append((n.id, before, dict(changes)))
        return res

    def _remove(self, nid: int) -> None:
        n = self.nodes.pop(nid, None)
        if n is None:
            return
        if n.parent in self.nodes:
            try:
                self.nodes[n.parent].children.remove(nid)
            except ValueError:
                pass
        for c in list(n.children):
            self._remove(c)

    # ---- queries --------------------------------------------------------
    def get(self, nid: int | None) -> Node | None:
        return self.nodes.get(nid) if nid is not None else None

    def ancestors(self, nid: int) -> Iterator[Node]:
        n = self.nodes.get(nid)
        while n is not None and n.parent is not None:
            n = self.nodes.get(n.parent)
            if n is not None:
                yield n

    def text_of(self, nid: int, limit: int = 200) -> str:
        """Visible-ish text content of a subtree, whitespace-collapsed."""
        out: list[str] = []
        total = 0

        def walk(i: int) -> None:
            nonlocal total
            if total > limit * 2:
                return
            n = self.nodes.get(i)
            if n is None:
                return
            if n.type == NODE_TEXT and n.text:
                out.append(n.text)
                total += len(n.text)
            elif n.type == NODE_ELEMENT and n.tag not in ("script", "style", "noscript", "template"):
                for c in n.children:
                    walk(c)

        walk(nid)
        return re.sub(r"\s+", " ", " ".join(out)).strip()[:limit]

    def find_descendant(self, nid: int, tags: set[str]) -> Node | None:
        n = self.nodes.get(nid)
        if n is None:
            return None
        for c in n.children:
            cn = self.nodes.get(c)
            if cn is None:
                continue
            if cn.tag in tags:
                return cn
            found = self.find_descendant(c, tags)
            if found:
                return found
        return None

    def find_by_attr(self, attr: str, value: str) -> Node | None:
        for n in self.nodes.values():
            if n.type == NODE_ELEMENT and n.attrs.get(attr) == value:
                return n
        return None

    def is_interactive(self, nid: int) -> bool:
        for n in [self.nodes.get(nid), *self.ancestors(nid)]:
            if n is None:
                continue
            if n.tag in INTERACTIVE_TAGS or n.attrs.get("role") in INTERACTIVE_ROLES:
                return True
            if "onclick" in n.attrs or n.attrs.get("tabindex") not in (None, "-1"):
                return True
            if n.attrs.get("href"):
                return True
        return False

    def is_hidden(self, nid: int) -> bool:
        """Hidden by inline style, hidden attribute, or an unshown error-like class, on self or ancestors."""
        for n in [self.nodes.get(nid), *self.ancestors(nid)]:
            if n is None or n.type != NODE_ELEMENT:
                continue
            if "hidden" in n.attrs and n.attrs.get("hidden") not in ("false",):
                return True
            if n.attrs.get("aria-hidden") == "true":
                return True
            if _HIDDEN_STYLE.search(str(n.attrs.get("style", ""))):
                return True
        return False

    def snapshot_info(self, nid: int) -> dict[str, Any]:
        n = self.nodes.get(nid)
        if n is None:
            return {"id": nid}
        return {"id": nid, "tag": n.tag, "attrs": dict(n.attrs), "text": self.text_of(nid, 120)}

    def viewport_scrollable(self) -> bool:
        return True


@dataclass
class MutationResult:
    added: list[int] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    text_changed: list[tuple[int, str | None, str | None]] = field(default_factory=list)
    attr_changed: list[tuple[int, dict[str, Any], dict[str, Any]]] = field(default_factory=list)
    removed_text: dict[int, list[str]] = field(default_factory=dict)  # parent id → old text

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.text_changed or self.attr_changed)


def class_shown_transition(before: dict[str, Any], after: dict[str, Any]) -> bool | None:
    """True if a 'shown' class was added, False if removed, None if no class change of that kind."""
    if "class" not in after:
        return None
    b = bool(_SHOWN_CLASS.search(str(before.get("class") or "")))
    a = bool(_SHOWN_CLASS.search(str(after.get("class") or "")))
    if a and not b:
        return True
    if b and not a:
        return False
    return None


def style_shown_transition(before: dict[str, Any], after: dict[str, Any]) -> bool | None:
    if "style" not in after:
        return None
    b_hidden = bool(_HIDDEN_STYLE.search(str(before.get("style") or "")))
    a_hidden = bool(_HIDDEN_STYLE.search(str(after.get("style") or "")))
    if b_hidden and not a_hidden:
        return True
    if a_hidden and not b_hidden:
        return False
    if not before.get("style") and re.search(r"display\s*:\s*(block|flex|grid|inline|inline-block|table)", str(after.get("style") or ""), re.I):
        return True
    return None
