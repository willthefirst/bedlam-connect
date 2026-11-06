"""
rrweb recording → Timeline. Deterministic; no LLM.

Input shape (what the snippet sends, merged per visit):
  {"visitorId": ..., "visitId": ..., "userId": ..., "events": [rrweb eventWithTime, ...]}
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from . import naming
from .config import TimelineConfig
from .dom import DOM, NODE_ELEMENT, class_shown_transition, style_shown_transition
from .model import Moment, Timeline
from .signals import apply_signals

# rrweb constants
EV_SNAPSHOT, EV_INCREMENTAL, EV_META, EV_CUSTOM, EV_PLUGIN = 2, 3, 4, 5, 6
SRC_MUTATION, SRC_MOUSEMOVE, SRC_MOUSE, SRC_SCROLL, SRC_VIEWPORT, SRC_INPUT, SRC_TOUCHMOVE = 0, 1, 2, 3, 4, 5, 6
SRC_LOG, SRC_SELECTION = 11, 14
MI_CLICK, MI_DBLCLICK, MI_FOCUS, MI_BLUR, MI_TOUCHSTART = 2, 4, 5, 6, 7

_ERROR_WORDS = re.compile(r"\b(required|invalid|incorrect|failed|failure|error|try again|not found|wrong|unable|cannot|can't|denied|expired)\b", re.I)
_ERROR_CLASS = re.compile(r"(error|invalid|alert|toast|warning|danger|validation)", re.I)
_MODAL_CLASS = re.compile(r"(modal|dialog|overlay|drawer|popover|lightbox)", re.I)
_SPINNER_CLASS = re.compile(r"(spinner|loading|loader|skeleton|progress)", re.I)
_SPINNER_WORDS = re.compile(r"\b(loading|please wait|creating|saving|processing)\b", re.I)


def _path(url: str) -> str:
    p = urlparse(url)
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def _host(url: str) -> str:
    return urlparse(url).netloc


def _device(ua: str, viewport: list[int] | None) -> dict[str, Any]:
    ua_l = ua.lower()
    mobile = any(k in ua_l for k in ("mobile", "iphone", "android", "ipad"))
    browser = "Chrome"
    if "edg/" in ua_l:
        browser = "Edge"
    elif "firefox" in ua_l:
        browser = "Firefox"
    elif "chrome" in ua_l or "crios" in ua_l:
        browser = "Chrome"
    elif "safari" in ua_l:
        browser = "Safari"
    return {"mobile": mobile, "browser": browser, "viewport": viewport or [], "user_agent": ua[:200]}


class _Builder:
    def __init__(self, cfg: TimelineConfig) -> None:
        self.cfg = cfg
        self.dom = DOM()
        self.moments: list[Moment] = []
        self.t0: float | None = None
        self.pages: list[str] = []
        self.current_url: str | None = None
        self.referrer: str | None = None
        self.device: dict[str, Any] = {}
        self.user_id: str | None = None
        self.facts: dict[str, Any] = {}
        self.pending_input: dict[int, Moment] = {}  # node id → moment being updated
        self.scroll_start: tuple[float, int] | None = None  # (t, y)
        self.last_scroll_y = 0
        self.classified: dict[int, str] = {}  # node id → kind (error/modal/spinner) for show/hide tracking
        self.spinner_shown_at: dict[int, float] = {}
        self.hover_track: list[tuple[float, str, int]] = []  # (t, name, nid) from mousemove positions

    # ------------------------------------------------------------------
    def t(self, ts: int) -> float:
        return round((ts - (self.t0 or ts)) / 1000.0, 1)

    def add(self, t: float, kind: str, text: str, **kw: Any) -> Moment:
        m = Moment(t=t, kind=kind, text=text, url=self.current_url, **kw)  # type: ignore[arg-type]
        self.moments.append(m)
        return m

    # ------------------------------------------------------------------
    def run(self, events: list[dict[str, Any]]) -> None:
        for i, ev in enumerate(events):
            ts = ev["timestamp"]
            if self.t0 is None:
                self.t0 = ts
            typ = ev["type"]
            data = ev.get("data") or {}
            if typ == EV_META:
                self.on_meta(i, ts, data)
            elif typ == EV_SNAPSHOT:
                self.dom.load_snapshot(data["node"])
                self.classified.clear()
            elif typ == EV_CUSTOM:
                self.on_custom(i, ts, data)
            elif typ == EV_INCREMENTAL:
                self.on_incremental(i, ts, data)
            elif typ == EV_PLUGIN:
                self.on_plugin(i, ts, data)
        self.flush_scroll(None)
        self.flush_hover(None)

    # ------------------------------------------------------------------
    def on_meta(self, i: int, ts: int, data: dict[str, Any]) -> None:
        self.flush_scroll(self.t(ts))
        self.flush_hover(self.t(ts))
        url = data.get("href", "")
        self.current_url = url
        path = _path(url)
        self.pages.append(path)
        self.add(self.t(ts), "action", f"page {path}", evidence={"event": i, "href": url})
        self.pending_input.clear()
        self.last_scroll_y = 0

    def on_custom(self, i: int, ts: int, data: dict[str, Any]) -> None:
        tag = data.get("tag")
        p = data.get("payload") or {}
        t = self.t(ts)
        if tag == "visit_meta":
            ref = p.get("referrer") or ""
            if not self.device:
                self.device = _device(p.get("userAgent", ""), p.get("viewport"))
                self.referrer = ref or None
            # annotate the page line with an external referrer
            if ref and self.current_url and _host(ref) != _host(self.current_url) and self.moments:
                last = self.moments[-1]
                if last.text.startswith("page ") and "(from" not in last.text:
                    last.text += f" (from {_host(ref)})"
            if p.get("userId") and not self.user_id:
                self.user_id = p["userId"]
        elif tag == "url":  # SPA navigation
            url = p.get("href", "")
            if url != self.current_url:
                self.flush_scroll(t)
                self.flush_hover(t)
                self.current_url = url
                self.pages.append(_path(url))
                self.add(t, "action", f"page {_path(url)}", evidence={"event": i, "href": url})
                self.pending_input.clear()
        elif tag == "visibility":
            self.flush_hover(t)
            state = p.get("state")
            self.add(t, "meta", "tab hidden" if state == "hidden" else "tab visible", evidence={"event": i})
        elif tag == "js_error":
            self.add(t, "screen", f'js error: "{str(p.get("message", ""))[:120]}"', evidence={"event": i})
        elif tag == "identify":
            self.user_id = p.get("userId") or self.user_id
            if p.get("facts"):
                self.facts.update(p["facts"])
            self.add(t, "meta", f"identified as user {self.user_id}", evidence={"event": i})
        elif tag == "visit_end":
            self.add(t, "meta", "visit ended", evidence={"event": i})
        elif tag == "pagehide":
            pass

    def on_plugin(self, i: int, ts: int, data: dict[str, Any]) -> None:
        if data.get("plugin") == "rrweb/console@1":
            payload = data.get("payload") or {}
            if payload.get("level") == "error":
                msg = " ".join(str(x) for x in payload.get("payload") or [])[:120]
                self.add(self.t(ts), "screen", f'js error: "{msg}"', evidence={"event": i})

    # ------------------------------------------------------------------
    def on_incremental(self, i: int, ts: int, d: dict[str, Any]) -> None:
        src = d.get("source")
        t = self.t(ts)
        if src == SRC_MUTATION:
            self.on_mutation(i, t, d)
            return
        if src in (SRC_MOUSEMOVE, SRC_TOUCHMOVE):
            for pos in d.get("positions") or []:
                nid = pos.get("id")
                if nid is None:
                    continue
                target = naming.interactive_target(self.dom, nid)
                if target is None:
                    continue
                pt = round(t + (pos.get("timeOffset") or 0) / 1000.0, 1)
                self.hover_track.append((pt, naming.name(self.dom, target.id), target.id))
            return
        # any other interaction ends a scroll/hover group
        self.flush_scroll(t)
        if src == SRC_MOUSE:
            self.on_mouse(i, t, d)
        elif src == SRC_INPUT:
            self.on_input(i, t, d)
        elif src == SRC_SCROLL:
            y = int(d.get("y") or 0)
            if self.scroll_start is None:
                self.scroll_start = (t, self.last_scroll_y)
            self.last_scroll_y = y
            self._scroll_pending_until = t + 1.0
        elif src == SRC_VIEWPORT:
            self.device["viewport"] = [d.get("width"), d.get("height")]
        elif src == SRC_SELECTION:
            ranges = d.get("ranges") or []
            if ranges:
                nid = ranges[0].get("start")
                self.add(t, "action", f"selected text in {naming.name(self.dom, nid)}", evidence={"event": i, "node": nid})

    def on_mouse(self, i: int, t: float, d: dict[str, Any]) -> None:
        mtype = d.get("type")
        nid = d.get("id")
        n = self.dom.get(nid)
        if mtype in (MI_CLICK, MI_DBLCLICK, MI_TOUCHSTART) and n is not None:
            self.flush_hover(t)
            label = naming.name(self.dom, nid)
            verb = "double-click" if mtype == MI_DBLCLICK else "click"
            if self.moments and self.moments[-1].evidence.get("focus") and self.moments[-1].element == label and t - self.moments[-1].t <= 0.5:
                return
            self.add(
                t,
                "action",
                f"{verb} {label}",
                element=label,
                evidence={"event": i, "node": nid, "interactive": self.dom.is_interactive(nid)},
            )
        elif mtype == MI_FOCUS and n is not None and n.tag in ("input", "textarea", "select"):
            label = naming.name(self.dom, nid)
            if self.moments and self.moments[-1].element == label and self.moments[-1].text.startswith("click "):
                self.moments[-1].text = f"focus {label}"
                self.moments[-1].evidence["focus"] = True
            else:
                self.add(t, "action", f"focus {label}", element=label, evidence={"event": i, "node": nid, "focus": True})
        elif mtype == MI_BLUR and nid in self.pending_input:
            self.pending_input.pop(nid, None)

    def on_input(self, i: int, t: float, d: dict[str, Any]) -> None:
        nid = d.get("id")
        n = self.dom.get(nid)
        if n is None:
            return
        text = str(d.get("text") or "")
        if n.tag == "input" and n.attrs.get("type") in ("checkbox", "radio"):
            label = naming.name(self.dom, nid)
            state = "checked" if d.get("isChecked") else "unchecked"
            self.add(t, "action", f"{state} {label}", element=label, evidence={"event": i, "node": nid})
            return
        if n.tag == "select":
            label = naming.name(self.dom, nid)
            self.add(t, "action", f"chose an option in {label}", element=label, evidence={"event": i, "node": nid})
            return
        label = naming.name(self.dom, nid)
        m = self.pending_input.get(nid)
        if m is None:
            m = self.add(t, "action", "", element=label, evidence={"event": i, "node": nid, "input": True})
            self.pending_input[nid] = m
        m.text = f"typed in {label} ({len(text)} chars, masked)" if text else f"cleared {label}"
        m.evidence["chars"] = len(text)

    def flush_scroll(self, t: float | None) -> None:
        if self.scroll_start is None:
            return
        st, y0 = self.scroll_start
        y1 = self.last_scroll_y
        self.scroll_start = None
        if abs(y1 - y0) < 40:
            return
        if y1 <= 20:
            txt = "scrolled back to top"
        else:
            txt = f"scrolled {'down' if y1 > y0 else 'up'} to {y1}px"
        self.add(st, "action", txt, evidence={"scroll": [y0, y1]})

    def flush_hover(self, t: float | None) -> None:
        """Collapse mousemove positions into hover-dwell lines and oscillation signals."""
        if not self.hover_track:
            return
        track = self.hover_track
        self.hover_track = []
        end_t = t if t is not None else track[-1][0]
        groups: list[tuple[float, float, str]] = []  # (start, end, name)
        for pt, label, _nid in track:
            if groups and groups[-1][2] == label:
                groups[-1] = (groups[-1][0], pt, label)
            else:
                if groups:
                    groups[-1] = (groups[-1][0], pt, groups[-1][2])
                groups.append((pt, pt, label))
        if groups:
            groups[-1] = (groups[-1][0], end_t, groups[-1][2])
        cfg = self.cfg.signals
        for start, end, label in groups:
            dur = end - start
            if dur >= cfg.hover_dwell_s and '"' in label:
                self.add(start, "signal", f"hover {label} ({dur:.0f}s)", element=label, evidence={"hover_s": round(dur, 1)})
        # oscillation between two labels
        seq = [g for g in groups if '"' in g[2]]
        k = 0
        while k + 2 * cfg.oscillation_min - 1 < len(seq) + 1 and k < len(seq):
            a = seq[k][2]
            j = k
            switches = 0
            b: str | None = None
            while j + 1 < len(seq) and seq[j + 1][0] - seq[k][0] <= cfg.oscillation_window_s:
                nxt = seq[j + 1][2]
                if b is None and nxt != a:
                    b = nxt
                if nxt not in (a, b):
                    break
                if nxt != seq[j][2]:
                    switches += 1
                j += 1
            if b is not None and switches >= 2 * cfg.oscillation_min - 2:
                times = (switches + 1) // 2
                self.add(seq[k][0], "signal", f"back-and-forth between {a} and {b} ×{times} ({seq[j][1] - seq[k][0]:.0f}s)", evidence={"oscillation": [a, b], "hover_s": round(seq[j][1] - seq[k][0], 1)})
                k = j + 1
            else:
                k += 1

    # ------------------------------------------------------------------
    def on_mutation(self, i: int, t: float, d: dict[str, Any]) -> None:
        res = self.dom.apply_mutation(d)
        if res.is_empty():
            return
        # update pending input labels (rare) — nothing to do
        lines = 0
        cap = self.cfg.signals.max_screen_lines_per_mutation
        added_set = set(res.added)
        seen_parents: set[int] = set()
        for nid in res.added:
            n = self.dom.get(nid)
            if n is None or n.parent in added_set:
                continue
            if n.type != NODE_ELEMENT:
                parent = self.dom.get(n.parent)
                if n.type == 3 and parent is not None and parent.id not in seen_parents and parent.tag not in ("script", "style", "input", "textarea") and lines < cap:
                    seen_parents.add(parent.id)
                    old = " ".join(res.removed_text.get(parent.id, [])).strip()
                    new = self.dom.text_of(parent.id, 60)
                    if new and new != old:
                        pname = naming.context_label(self.dom, parent.id)
                        self.add(t, "screen", f'text changed in {pname}: "{old[:40]}" → "{new[:40]}"' if old else f'text appeared in {pname}: "{new[:40]}"', evidence={"event": i, "node": parent.id})
                        lines += 1
                continue
            if self.dom.is_hidden(nid):
                continue
            kind, txt = self.classify(nid)
            if kind and lines < cap:
                self.emit_shown(t, i, nid, kind, txt)
                lines += 1
        for nid, before, after in res.attr_changed:
            n = self.dom.get(nid)
            if n is None:
                continue
            shown = class_shown_transition(before, after)
            if shown is None:
                shown = style_shown_transition(before, after)
            if shown is None:
                continue
            kind, txt = self.classify(nid)
            if not kind:
                continue
            if shown and lines < cap:
                self.emit_shown(t, i, nid, kind, txt)
                lines += 1
            elif not shown and lines < cap:
                self.emit_hidden(t, i, nid, kind, txt)
                lines += 1
        for rem in res.removed:
            kind = self.classified.pop(rem.get("id"), None)
            if kind in ("modal", "spinner") and lines < cap:
                self.emit_hidden(t, i, rem["id"], kind, rem.get("text") or "")
                lines += 1
        for nid, old, new in res.text_changed:
            n = self.dom.get(nid)
            if n is None or n.parent is None or lines >= cap:
                continue
            parent = self.dom.get(n.parent)
            if parent is None or parent.tag in ("input", "textarea", "script", "style"):
                continue
            o, nw = (old or "").strip(), (new or "").strip()
            if o and nw and o != nw and len(nw) <= 60:
                self.add(t, "screen", f'text changed in {naming.context_label(self.dom, parent.id)}: "{o[:40]}" → "{nw[:40]}"', evidence={"event": i, "node": nid})
                lines += 1

    def classify(self, nid: int) -> tuple[str | None, str]:
        n = self.dom.get(nid)
        if n is None:
            return None, ""
        a = n.attrs
        ident = f"{a.get('class', '')} {a.get('id', '')} {a.get('data-testid', '')}"
        text = self.dom.text_of(nid, 160)
        role = a.get("role")
        if role in ("alert", "alertdialog") or a.get("aria-live") or _ERROR_CLASS.search(ident) or (text and _ERROR_WORDS.search(text) and len(text) < 160 and n.tag not in ("form", "main", "body", "section")):
            if text:
                return "error", text
        if role == "dialog" or n.tag == "dialog" or _MODAL_CLASS.search(ident):
            h = self.dom.find_descendant(nid, {"h1", "h2", "h3", "h4"})
            return "modal", (self.dom.text_of(h.id, 80) if h else text[:80])
        if a.get("aria-busy") == "true" or _SPINNER_CLASS.search(ident) or (text and _SPINNER_WORDS.search(text) and len(text) < 60):
            return "spinner", text[:60]
        if text and len(text) >= self.cfg.signals.content_min_chars:
            return "content", text[:80]
        return None, ""

    def emit_shown(self, t: float, i: int, nid: int, kind: str, txt: str) -> None:
        self.classified[nid] = kind
        if kind == "error":
            self.add(t, "screen", f'error shown: "{txt[:120]}"', evidence={"event": i, "node": nid})
        elif kind == "modal":
            self.add(t, "screen", f'dialog opened: "{txt}"' if txt else "dialog opened", evidence={"event": i, "node": nid})
        elif kind == "spinner":
            self.spinner_shown_at[nid] = t
            self.add(t, "screen", f'loading… ("{txt}")' if txt else "loading…", evidence={"event": i, "node": nid})
        elif kind == "content":
            self.add(t, "screen", f'content appeared: "{txt}…"', evidence={"event": i, "node": nid})

    def emit_hidden(self, t: float, i: int, nid: int, kind: str, txt: str) -> None:
        self.classified.pop(nid, None)
        if kind == "modal":
            self.add(t, "screen", "dialog closed", evidence={"event": i, "node": nid})
        elif kind == "spinner":
            started = self.spinner_shown_at.pop(nid, None)
            dur = f" ({t - started:.1f}s)" if started is not None else ""
            self.add(t, "screen", f"loaded{dur}", evidence={"event": i, "node": nid})
        elif kind == "error":
            self.add(t, "screen", "error cleared", evidence={"event": i, "node": nid})


def build_timeline(recording: dict[str, Any], cfg: TimelineConfig | None = None) -> Timeline:
    cfg = cfg or TimelineConfig()
    events = sorted(recording.get("events") or [], key=lambda e: e["timestamp"])
    if not events:
        raise ValueError("recording has no events")
    b = _Builder(cfg)
    b.run(events)
    moments = sorted(b.moments, key=lambda m: m.t)
    moments = [m for m in moments if m.text]
    started = datetime.fromtimestamp(events[0]["timestamp"] / 1000, tz=timezone.utc)
    ended = datetime.fromtimestamp(events[-1]["timestamp"] / 1000, tz=timezone.utc)
    pages: list[str] = []
    for p in b.pages:
        if not pages or pages[-1] != p:
            pages.append(p)
    tl = Timeline(
        visit_id=recording.get("visitId") or "",
        visitor_id=recording.get("visitorId") or "",
        user_id=recording.get("userId") or b.user_id,
        started_at=started,
        ended_at=ended,
        entry_url=pages[0] if pages else "/",
        referrer=b.referrer,
        device=b.device,
        moments=moments,
        pages=pages,
        facts_from_site=b.facts,
    )
    apply_signals(tl, cfg.signals)
    tl.moments.sort(key=lambda m: m.t)
    return tl
