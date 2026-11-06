"""Turn a DOM node into a short human label like `button "Start trial"` or `field "Email"`."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .dom import DOM, NODE_ELEMENT, Node

MAX_LABEL = 60

ROLE_BY_TAG = {
    "a": "link",
    "button": "button",
    "select": "select",
    "textarea": "field",
    "summary": "disclosure",
    "option": "option",
    "img": "image",
    "video": "video",
    "nav": "nav",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
    "h4": "heading",
    "li": "list item",
    "td": "cell",
    "th": "cell",
    "p": "text",
    "span": "text",
    "div": "area",
    "section": "section",
    "label": "label",
    "form": "form",
}
INPUT_ROLES = {
    "checkbox": "checkbox",
    "radio": "radio",
    "submit": "button",
    "button": "button",
    "range": "slider",
    "file": "file picker",
    "search": "search field",
}
_ws = re.compile(r"\s+")


def _clean(s: str | None) -> str:
    if not s:
        return ""
    s = _ws.sub(" ", str(s)).strip()
    return s if len(s) <= MAX_LABEL else s[: MAX_LABEL - 1].rstrip() + "…"


def role_of(n: Node) -> str:
    if n.tag == "input":
        t = str(n.attrs.get("type", "text")).lower()
        return INPUT_ROLES.get(t, "field")
    r = n.attrs.get("role")
    if r in ("button", "link", "tab", "menuitem", "checkbox", "radio", "switch", "dialog", "alert", "textbox"):
        return {"menuitem": "menu item", "textbox": "field"}.get(r, r)
    return ROLE_BY_TAG.get(n.tag or "", n.tag or "node")


def _label_for_field(dom: DOM, n: Node) -> str:
    nid_attr = n.attrs.get("id")
    if nid_attr:
        lab = dom.find_by_attr("for", str(nid_attr))
        if lab is not None:
            t = _clean(dom.text_of(lab.id))
            if t:
                return t
    for anc in dom.ancestors(n.id):
        if anc.tag == "label":
            t = _clean(dom.text_of(anc.id))
            if t:
                return t
    return ""


def _nearest_heading(dom: DOM, n: Node) -> str:
    for anc in dom.ancestors(n.id):
        h = dom.find_descendant(anc.id, {"h1", "h2", "h3", "h4"})
        if h is not None:
            t = _clean(dom.text_of(h.id))
            if t:
                return t
    return ""


def _section_heading(dom: DOM, n: Node) -> str:
    """Heading of the nearest enclosing section-like ancestor (not the whole page)."""
    for anc in dom.ancestors(n.id):
        if anc.tag in ("body", "html", "main", "form"):
            return ""
        h = dom.find_descendant(anc.id, {"h1", "h2", "h3", "h4"})
        if h is not None:
            return _clean(dom.text_of(h.id))
    return ""


def interactive_target(dom: DOM, nid: int) -> Node | None:
    """Walk up from a clicked node to the thing a person would say they clicked."""
    n = dom.get(nid)
    if n is None:
        return None
    chain = [n, *dom.ancestors(nid)]
    for c in chain:
        if c.type != NODE_ELEMENT:
            continue
        if c.tag in ("a", "button", "input", "select", "textarea", "summary", "label"):
            return c
        if c.attrs.get("role") in ("button", "link", "tab", "menuitem", "checkbox", "radio", "switch", "option"):
            return c
    # not interactive: pick the closest element with its own id/class as a landmark
    for c in chain:
        if c.type == NODE_ELEMENT and (c.attrs.get("id") or c.attrs.get("data-testid")):
            return c
    return n if n.type == NODE_ELEMENT else (chain[1] if len(chain) > 1 else None)


def name(dom: DOM, nid: int, *, resolve_target: bool = True) -> str:
    n = interactive_target(dom, nid) if resolve_target else dom.get(nid)
    if n is None:
        return "unknown element"
    if n.type != NODE_ELEMENT:
        return "text"
    role = role_of(n)
    a = n.attrs
    label = _clean(a.get("aria-label"))
    if not label and n.tag in ("input", "select", "textarea"):
        label = _label_for_field(dom, n)
    if not label and n.tag == "input" and a.get("type") in ("submit", "button"):
        label = _clean(a.get("value"))
    if not label and role in ("area", "section", "list item", "cell", "form"):
        h = dom.find_descendant(n.id, {"h1", "h2", "h3", "h4"})
        if h is not None:
            label = _clean(dom.text_of(h.id))
    if not label and n.tag not in ("input", "select", "textarea"):
        label = _clean(dom.text_of(n.id))
    if not label:
        label = _clean(a.get("placeholder")) or _clean(a.get("title")) or _clean(a.get("alt"))
    if not label:
        label = _clean(a.get("name")) or _clean(a.get("data-testid"))
    if not label and role in ("area", "section", "text", "list item", "cell"):
        label = _nearest_heading(dom, n)
    if not label:
        label = _clean(a.get("id"))
    out = f'{role} "{label}"' if label else role
    if role in ("button", "link", "checkbox", "radio") and label:
        ctx = _section_heading(dom, n)
        if ctx and ctx.lower() not in label.lower():
            out += f' in "{ctx}"'
    if n.tag == "a" and a.get("href"):
        path = urlparse(str(a["href"])).path or str(a["href"])
        if path and path not in out:
            out += f" → {path}"
    return out


def is_masked_input(n: Node | None) -> bool:
    return n is not None and n.tag in ("input", "textarea") or (n is not None and n.attrs.get("contenteditable") == "true")


def context_label(dom: DOM, nid: int) -> str:
    """Label for *where* something changed: the nearest heading above it, else the element's own name."""
    n = dom.get(nid)
    if n is None:
        return "page"
    for anc in [n, *dom.ancestors(nid)]:
        if anc.tag in ("h1", "h2", "h3", "h4"):
            return f'heading "{_clean(dom.text_of(anc.id))}"'
        h = dom.find_descendant(anc.id, {"h1", "h2", "h3", "h4"})
        if h is not None and anc.tag not in ("body", "html", "main"):
            return f'"{_clean(dom.text_of(h.id))}" section'
    return name(dom, nid, resolve_target=False)
