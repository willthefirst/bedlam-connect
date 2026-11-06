"""Signed HTTP client for the two consumer routes, plus the startup check."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

log = logging.getLogger("storyteller.hooks")
HEALTHCHECK_ID = "__storyteller_healthcheck__"


def sign(secret: str, timestamp: str, body: str) -> str:
    return "v1=" + hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str, body: str | bytes, signature: str, max_skew: int = 300) -> bool:
    """For consumers: True if the request is authentic and fresh."""
    try:
        if abs(time.time() - int(timestamp)) > max_skew:
            return False
    except (TypeError, ValueError):
        return False
    if isinstance(body, bytes):
        body = body.decode()
    return hmac.compare_digest(sign(secret, timestamp, body), signature or "")


class ConsumerHooks:
    def __init__(self, cfg: dict[str, Any], secret: str) -> None:
        self.base = (cfg.get("base_url") or "").rstrip("/")
        routes = cfg.get("routes") or {}
        self.write_route = routes.get("write_story") or "/internal/storyteller/stories"
        self.read_route = routes.get("read_visitor") or "/internal/storyteller/visitors/{id}"
        self.secret = secret
        self.timeout = float(cfg.get("timeout_seconds", 5))
        self.enabled = bool(self.base)

    def _headers(self, body: str) -> dict[str, str]:
        ts = str(int(time.time()))
        return {"Content-Type": "application/json", "X-Storyteller-Timestamp": ts, "X-Storyteller-Signature": sign(self.secret, ts, body)}

    def read_visitor(self, visitor_id: str) -> dict[str, Any] | None:
        """None = new visitor (404) or hook unavailable; the caller marks history_available accordingly."""
        if not self.enabled:
            return None
        url = self.base + self.read_route.replace("{id}", visitor_id)
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.get(url, headers=self._headers(""))
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {}
        except Exception as e:  # noqa: BLE001
            log.warning("read_visitor failed for %s: %s", visitor_id, e)
            return None

    def write_story(self, story: dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        body = json.dumps(story)
        url = self.base + self.write_route
        delay = 1.0
        for attempt in range(3):
            try:
                with httpx.Client(timeout=max(self.timeout, 15)) as c:
                    r = c.post(url, content=body, headers=self._headers(body))
                if 200 <= r.status_code < 300:
                    return True
                log.warning("write_story got %s (attempt %d): %s", r.status_code, attempt + 1, r.text[:200])
            except Exception as e:  # noqa: BLE001
                log.warning("write_story failed (attempt %d): %s", attempt + 1, e)
            time.sleep(delay)
            delay *= 3
        return False

    def startup_check(self) -> dict[str, Any]:
        if not self.enabled:
            return {"configured": False, "ok": False, "detail": "consumer.base_url not set; stories will only be logged"}
        out: dict[str, Any] = {"configured": True}
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.get(self.base + self.read_route.replace("{id}", HEALTHCHECK_ID), headers=self._headers(""))
            out["read_visitor"] = r.status_code
            body = json.dumps({"schema_version": "1", "healthcheck": True})
            with httpx.Client(timeout=self.timeout) as c:
                r2 = c.post(self.base + self.write_route, content=body, headers=self._headers(body))
            out["write_story"] = r2.status_code
            out["ok"] = r.status_code in (200, 404) and 200 <= r2.status_code < 300
        except Exception as e:  # noqa: BLE001
            out["ok"] = False
            out["detail"] = str(e)
        if not out.get("ok"):
            log.error("consumer hook check FAILED: %s", out)
        return out
