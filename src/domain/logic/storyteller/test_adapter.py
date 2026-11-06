"""Tests for the Storyteller consumer adapter: signature check + store."""

from __future__ import annotations

import sqlite3

import pytest

from src.domain.logic.storyteller.adapter import Store, sign, verify_signature

SECRET = "shared-secret"
NOW = 1_800_000_000.0


def test_signature_roundtrip_matches_protocol_shape():
    """`v1=` + hex HMAC-SHA256 over `"<timestamp>.<raw body>"`, as the
    service computes it (`vendor/storyteller/packages/service/storyteller/hooks.py`)."""
    ts = str(int(NOW))
    body = b'{"visit_id": "v1"}'
    sig = sign(SECRET, ts, body)
    assert sig.startswith("v1=") and len(sig) == 3 + 64
    assert verify_signature(SECRET, ts, body, sig, now=NOW)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda ts, body, sig: ("", body, sig), id="missing-timestamp"),
        pytest.param(lambda ts, body, sig: ("abc", body, sig), id="junk-timestamp"),
        pytest.param(
            lambda ts, body, sig: (str(int(NOW) - 301), body, sig), id="stale"
        ),
        pytest.param(lambda ts, body, sig: (ts, body + b" ", sig), id="body-tamper"),
        pytest.param(lambda ts, body, sig: (ts, body, ""), id="missing-signature"),
        pytest.param(
            lambda ts, body, sig: (ts, body, sign("other", ts, body)),
            id="wrong-secret",
        ),
    ],
)
def test_signature_rejects_tampering_and_replay(mutate):
    ts = str(int(NOW))
    body = b'{"visit_id": "v1"}'
    ts2, body2, sig2 = mutate(ts, body, sign(SECRET, ts, body))
    assert not verify_signature(SECRET, ts2, body2, sig2, now=NOW)


def test_stale_signature_is_rejected_by_wall_clock_too():
    ts = str(int(NOW) - 10_000)
    body = b"{}"
    assert not verify_signature(SECRET, ts, body, sign(SECRET, ts, body))


def _story(visit_id="v1", visitor_id="vis-1", **overrides):
    story = {
        "schema_version": "1",
        "visit_id": visit_id,
        "visitor_id": visitor_id,
        "user_id": None,
        "started_at": "2026-11-05T10:00:00",
        "outcome": {"label": "completed_signup", "confidence": 0.8},
        "narrative": "They signed up.",
        "tags": ["signup"],
        "visitor_summary": "A new member.",
        "trajectory": [{"visit_id": visit_id, "outcome": "completed_signup"}],
    }
    story.update(overrides)
    return story


def test_store_is_lazy_and_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "storyteller.db"
    store = Store(path)
    assert not path.exists(), "constructing a Store must not touch disk"
    assert store.recent() == []
    assert path.exists()
    tables = {
        r[0]
        for r in sqlite3.connect(path).execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"stories", "visitors", "facts", "instructions"} <= tables


def test_unknown_visitor_is_none(tmp_path):
    assert Store(tmp_path / "s.db").visitor("nobody") is None


def test_save_story_then_read_visitor_returns_protocol_shape(tmp_path):
    store = Store(tmp_path / "s.db")
    store.save_story(_story())
    store.add_fact("vis-1", "This is a colleague testing the site", weight="high")
    store.set_instruction("global", "Be brief.")
    store.set_instruction("visitor:vis-1", "They are an expert.")

    memory = store.visitor("vis-1")
    assert memory is not None
    assert memory["schema_version"] == "1"
    assert memory["summary"] == "A new member."
    assert memory["trajectory"] == [{"visit_id": "v1", "outcome": "completed_signup"}]
    assert [f["text"] for f in memory["facts"]] == [
        "This is a colleague testing the site"
    ]
    assert memory["facts"][0]["weight"] == "high"
    assert memory["instructions"] == {
        "global": "Be brief.",
        "visitor": "They are an expert.",
    }


def test_facts_alone_make_a_visitor_known(tmp_path):
    """An admin can seed a fact before the visitor's first story lands;
    the read hook must then return it rather than 404."""
    store = Store(tmp_path / "s.db")
    store.add_fact("vis-9", "My friend Sam")
    memory = store.visitor("vis-9")
    assert memory is not None
    assert memory["summary"] == "" and memory["trajectory"] == []
    assert memory["facts"][0]["text"] == "My friend Sam"


def test_save_story_upserts_by_visit_and_keeps_full_json(tmp_path):
    store = Store(tmp_path / "s.db")
    store.save_story(_story(narrative="first draft"))
    store.save_story(_story(narrative="regenerated"))
    store.save_story(_story(visit_id="v0", started_at="2026-11-04T10:00:00"))

    recent = store.recent()
    assert [s["visit_id"] for s in recent] == [
        "v1",
        "v0",
    ], "newest first, one per visit"
    assert recent[0]["narrative"] == "regenerated"
    assert recent[0]["outcome"] == {"label": "completed_signup", "confidence": 0.8}
    assert store.recent(limit=1) == recent[:1]
