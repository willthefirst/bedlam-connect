import json
from pathlib import Path

import pytest

from storyteller.timeline import build_timeline

FIX = Path(__file__).resolve().parents[3] / "fixtures"


def load(name):
    return json.load(open(FIX / f"{name}.json"))


def texts(tl):
    return [m.text for m in tl.moments]


def test_compare_abandon_reads_the_story():
    tl = build_timeline(load("compare_abandon"))
    t = "\n".join(texts(tl))
    assert "page /pricing.html (from www.google.com)" in t
    assert "back-and-forth between" in t
    assert 'click button "Annual"' in t
    assert '"$29/mo" → "$290/yr"' in t
    assert 'click button "Start trial" in "Pro plan"' in t
    assert "page /signup.html?plan=pro" in t
    assert 'typed in field "Email"' in t
    assert 'still on field "Company name", no input' in t
    assert "away from tab for" in t
    assert 'error shown: "Company name is required"' in t
    assert "same error still shown" in t
    assert "left with a form partly filled (2 fields)" in t
    assert tl.pages == ["/pricing.html", "/signup.html?plan=pro"]
    assert tl.device["browser"] == "Chrome" and tl.device["mobile"] is False


def test_success_rage():
    tl = build_timeline(load("success_rage"))
    t = "\n".join(texts(tl))
    assert 'click link "Pricing"' in t
    assert "identified as user user_42" in t
    assert tl.user_id == "user_42"
    assert tl.facts_from_site == {"plan_interest": "team"}
    assert "loading…" in t and "loaded (" in t
    assert 'dialog opened: "Welcome aboard"' in t
    assert 'rage click on button "Go to dashboard" in "Welcome aboard" (×4' in t
    assert "left with a form partly filled" not in t


def test_bounce():
    tl = build_timeline(load("bounce"))
    assert tl.duration_s < 5
    assert texts(tl)[0].startswith("page /pricing.html (from news.ycombinator.com)")


def test_no_raw_ids_or_masked_values_in_text():
    for name in ("compare_abandon", "success_rage"):
        tl = build_timeline(load(name))
        txt = tl.render()
        assert "someone@example.com" not in txt
        assert "hunter2" not in txt
        assert "BigCo" not in txt
        assert "node" not in txt.lower().replace("nothing", "")


def test_render_is_fast():
    import time

    rec = load("compare_abandon")
    t0 = time.time()
    build_timeline(rec)
    assert time.time() - t0 < 2
