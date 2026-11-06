"""Derived signals computed over the moment list. All flagged kind="signal"."""
from __future__ import annotations

from .config import SignalConfig
from .model import Moment, Timeline


def _is_action(m: Moment) -> bool:
    return m.kind == "action"


def apply_signals(tl: Timeline, cfg: SignalConfig) -> None:
    ms = tl.moments
    _rage_clicks(tl, cfg)
    _dead_clicks(tl, cfg)
    _pauses_and_stalls(tl, cfg)
    _back_outs(tl, cfg)
    _form_abandon(tl, cfg)
    tl.moments.sort(key=lambda m: m.t)


def _rage_clicks(tl: Timeline, cfg: SignalConfig) -> None:
    out: list[Moment] = []
    ms = tl.moments
    i = 0
    while i < len(ms):
        m = ms[i]
        if m.kind == "action" and m.text.startswith("click ") and m.element:
            j = i
            while j + 1 < len(ms) and ms[j + 1].kind == "action" and ms[j + 1].text == m.text and ms[j + 1].t - ms[j].t <= cfg.rage_window_s:
                j += 1
            n = j - i + 1
            if n >= cfg.rage_clicks:
                out.append(Moment(t=m.t, kind="signal", text=f"rage click on {m.element} (×{n} in {ms[j].t - m.t:.1f}s)", element=m.element, url=m.url, evidence={"clicks": n, "first_event": m.evidence.get("event")}))
                i = j + 1
                continue
        out.append(m)
        i += 1
    tl.moments = out


def _dead_clicks(tl: Timeline, cfg: SignalConfig) -> None:
    ms = tl.moments
    extra: list[Moment] = []
    for idx, m in enumerate(ms):
        if m.kind != "action" or not m.text.startswith("click "):
            continue
        if m.evidence.get("interactive"):
            # interactive but nothing happened on screen afterwards → also dead
            pass
        reacted = False
        error_visible = False
        for prev in reversed(ms[:idx]):
            if prev.kind == "screen" and prev.text.startswith("error shown"):
                error_visible = True
                break
            if prev.kind == "screen" and prev.text.startswith("error cleared") or (prev.kind == "action" and prev.text.startswith("page ")):
                break
        for n in ms[idx + 1 :]:
            if n.t - m.t > cfg.dead_click_grace_s:
                break
            if n.kind == "screen" or (n.kind == "action" and n.text.startswith("page ")):
                reacted = True
                break
        if not reacted:
            if m.evidence.get("interactive"):
                # interactive elements often navigate or open things we can't see (external links, downloads). Only flag buttons.
                if m.element and m.element.startswith("button"):
                    txt = f"clicked {m.element} again; same error still shown" if error_visible else f"nothing visibly happened after clicking {m.element}"
                    extra.append(Moment(t=m.t, kind="signal", text=txt, element=m.element, url=m.url, evidence={"dead": True}))
            else:
                extra.append(Moment(t=m.t, kind="signal", text=f"dead click on {m.element} (not interactive)", element=m.element, url=m.url, evidence={"dead": True}))
    tl.moments.extend(extra)


def _pauses_and_stalls(tl: Timeline, cfg: SignalConfig) -> None:
    ms = sorted(tl.moments, key=lambda m: m.t)
    extra: list[Moment] = []
    hidden_since: float | None = None
    last_action: Moment | None = None
    last_t = 0.0
    focused_field: Moment | None = None
    field_typed = False
    end_t = tl.duration_s

    def account_gap(from_t: float, to_t: float, anchor: Moment | None, is_end: bool = False) -> None:
        gap = to_t - from_t
        if anchor is not None and anchor.evidence.get("focus") and focused_field is anchor and not field_typed:
            return  # a field-stall line will cover this gap
        if gap >= cfg.pause_s and hidden_since is None:
            where = f' (on {anchor.element})' if anchor and anchor.element else (f" (on page {anchor.url and anchor.url.split('//',1)[-1].split('/',1)[-1] and '/' + anchor.url.split('//',1)[-1].split('/',1)[-1]})" if anchor and anchor.url else "")
            label = "no further activity" if is_end else "no activity"
            extra.append(Moment(t=from_t, kind="signal", text=f"{label} for {gap:.0f}s{where}", url=anchor.url if anchor else None, evidence={"gap_s": round(gap, 1)}))

    def stall_check(now: float) -> None:
        nonlocal focused_field
        if focused_field is not None and not field_typed:
            gap = now - focused_field.t
            if gap >= cfg.field_stall_s:
                extra.append(Moment(t=focused_field.t, kind="signal", text=f"still on {focused_field.element}, no input ({gap:.0f}s)", element=focused_field.element, url=focused_field.url, evidence={"stall_s": round(gap, 1)}))
            focused_field = None

    for m in ms:
        if m.kind == "meta" and m.text == "tab hidden":
            if last_action is not None and hidden_since is None:
                account_gap(last_t, m.t, last_action)
            stall_check(m.t)
            hidden_since = m.t
            continue
        if m.kind == "meta" and m.text == "tab visible":
            if hidden_since is not None:
                extra.append(Moment(t=hidden_since, kind="signal", text=f"away from tab for {m.t - hidden_since:.0f}s", evidence={"hidden_s": round(m.t - hidden_since, 1)}))
            hidden_since = None
            last_t = m.t
            continue
        if m.kind == "signal" and ("hover_s" in m.evidence or "oscillation" in m.evidence):
            if last_action is not None and hidden_since is None:
                account_gap(last_t, m.t, last_action)
            last_t = m.t + m.evidence.get("hover_s", 0.0)
            continue
        if m.kind != "action":
            continue
        if last_action is not None:
            account_gap(last_t, m.t, last_action)
        if focused_field is not None and m is not focused_field and not (m.evidence.get("input") and m.element == focused_field.element):
            stall_check(m.t)
        if m.evidence.get("focus"):
            focused_field = m
            field_typed = False
        elif m.evidence.get("input") and focused_field is not None and m.element == focused_field.element:
            field_typed = True
        elif m.text.startswith("page "):
            focused_field = None
        last_action = m
        last_t = m.t
    if last_action is not None and hidden_since is None:
        account_gap(last_t, end_t, last_action, is_end=True)
        stall_check(end_t)
    tl.moments.extend(extra)


def _back_outs(tl: Timeline, cfg: SignalConfig) -> None:
    pages = [m for m in sorted(tl.moments, key=lambda m: m.t) if m.kind == "action" and m.text.startswith("page ")]
    extra: list[Moment] = []
    for a, b, c in zip(pages, pages[1:], pages[2:]):
        pa, pb, pc = (x.text.split(" ")[1] for x in (a, b, c))
        if pa == pc and pb != pa and c.t - b.t <= cfg.back_out_s:
            extra.append(Moment(t=c.t, kind="signal", text=f"quick back-out from {pb} after {c.t - b.t:.0f}s", url=c.url, evidence={"back_out": pb}))
    tl.moments.extend(extra)


def _form_abandon(tl: Timeline, cfg: SignalConfig) -> None:
    ms = sorted(tl.moments, key=lambda m: m.t)
    last_page_idx = max((i for i, m in enumerate(ms) if m.kind == "action" and m.text.startswith("page ")), default=0)
    tail = ms[last_page_idx:]
    typed = {m.element for m in tail if m.evidence.get("input") and m.evidence.get("chars")}
    submitted = any(m.kind == "action" and m.text.startswith("click button") and any(w in m.text.lower() for w in ("submit", "create", "sign", "continue", "next", "save", "send", "pay", "register", "log in", "login")) for m in tail)
    succeeded = any(m.kind == "screen" and (m.text.startswith("dialog opened") or m.text.startswith("loaded")) for m in tail)
    if typed and not (submitted and succeeded):
        errors = [m for m in tail if m.kind == "screen" and m.text.startswith("error shown")]
        why = f"; last error: {errors[-1].text.split(': ',1)[1]}" if errors else ""
        tl.moments.append(Moment(t=tl.duration_s, kind="signal", text=f"left with a form partly filled ({len(typed)} field{'s' if len(typed) != 1 else ''}){why}", url=tail[-1].url if tail else None, evidence={"fields": sorted(e for e in typed if e)}))
