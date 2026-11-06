"""The Anthropic brain must send a request current Claude models accept."""
import json

import httpx

from storyteller.llm.anthropic import AnthropicBrain
from storyteller.llm.base import Message


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._p


def _fake_client(recorder, status=200, payload=None):
    payload = payload or {"content": [{"type": "text", "text": '{"ok": true}'}], "model": "m", "usage": {}}

    class C:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json, headers):
            recorder["url"] = url
            recorder["body"] = json
            return _Resp(status, payload)

    return C


def test_no_prefill_no_temperature(monkeypatch):
    rec = {}
    monkeypatch.setattr(httpx, "Client", _fake_client(rec))
    brain = AnthropicBrain({"api_key": "k", "model": "claude-sonnet-5-5"})
    comp = brain.complete("sys", [Message("user", "hi")], json=True)
    assert rec["url"] == "https://api.anthropic.com/v1/messages"
    assert "temperature" not in rec["body"]
    assert [m["role"] for m in rec["body"]["messages"]] == ["user"], "no assistant prefill"
    assert comp.text == '{"ok": true}'


def test_api_error_message_is_surfaced(monkeypatch):
    rec = {}
    monkeypatch.setattr(httpx, "Client", _fake_client(rec, 400, {"error": {"message": "temperature not supported"}}))
    brain = AnthropicBrain({"api_key": "k"})
    try:
        brain.complete("sys", [Message("user", "hi")])
    except RuntimeError as e:
        assert "400" in str(e) and "temperature not supported" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
