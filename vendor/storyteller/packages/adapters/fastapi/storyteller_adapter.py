"""
Storyteller reference adapter for FastAPI.

Drop this file into your app and mount it:

    from storyteller_adapter import make_router
    app.include_router(make_router(db_path="storyteller.db"))

It implements the two consumer functions at the default routes
(override with `prefix=`), verifies request signatures, stores everything in a
SQLite file you own, and serves a tiny viewer at /internal/storyteller/ui.

Env:  STORYTELLER_SECRET  (same value the service has)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
  visit_id TEXT PRIMARY KEY, visitor_id TEXT, user_id TEXT, started_at TEXT, outcome TEXT,
  narrative TEXT, tags TEXT, story JSON, received_at REAL
);
CREATE INDEX IF NOT EXISTS stories_visitor ON stories(visitor_id, started_at);
CREATE TABLE IF NOT EXISTS visitors (
  visitor_id TEXT PRIMARY KEY, user_id TEXT, summary TEXT, trajectory JSON, updated_at REAL
);
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, visitor_id TEXT, text TEXT, weight TEXT DEFAULT 'normal', added_at REAL
);
CREATE TABLE IF NOT EXISTS instructions (scope TEXT PRIMARY KEY, text TEXT, updated_at REAL);
"""


def verify_signature(secret: str, timestamp: str, body: bytes, signature: str, max_skew: int = 300) -> bool:
    try:
        if abs(time.time() - int(timestamp)) > max_skew:
            return False
    except (TypeError, ValueError):
        return False
    expected = "v1=" + hmac.new(secret.encode(), f"{timestamp}.{body.decode()}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        with closing(self._conn()) as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def save_story(self, s: dict[str, Any]) -> None:
        with closing(self._conn()) as c, c:
            c.execute(
                "INSERT OR REPLACE INTO stories VALUES (?,?,?,?,?,?,?,?,?)",
                (s["visit_id"], s.get("visitor_id"), s.get("user_id"), s.get("started_at"), (s.get("outcome") or {}).get("label"), s.get("narrative"), json.dumps(s.get("tags") or []), json.dumps(s), time.time()),
            )
            c.execute(
                "INSERT OR REPLACE INTO visitors VALUES (?,?,?,?,?)",
                (s.get("visitor_id"), s.get("user_id"), s.get("visitor_summary"), json.dumps(s.get("trajectory") or []), time.time()),
            )

    def visitor(self, visitor_id: str) -> dict[str, Any] | None:
        with closing(self._conn()) as c:
            v = c.execute("SELECT * FROM visitors WHERE visitor_id=?", (visitor_id,)).fetchone()
            facts = c.execute("SELECT text, weight, added_at FROM facts WHERE visitor_id=? ORDER BY added_at", (visitor_id,)).fetchall()
            ins = {r["scope"]: r["text"] for r in c.execute("SELECT scope, text FROM instructions").fetchall()}
        if v is None and not facts and not ins.get(f"visitor:{visitor_id}"):
            return None
        return {
            "schema_version": "1",
            "summary": v["summary"] if v else "",
            "trajectory": json.loads(v["trajectory"]) if v else [],
            "facts": [{"text": f["text"], "weight": f["weight"], "added_at": f["added_at"]} for f in facts],
            "instructions": {"global": ins.get("global", ""), "visitor": ins.get(f"visitor:{visitor_id}", "")},
        }

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with closing(self._conn()) as c:
            rows = c.execute("SELECT story FROM stories ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(r["story"]) for r in rows]

    def add_fact(self, visitor_id: str, text: str, weight: str = "normal") -> None:
        with closing(self._conn()) as c, c:
            c.execute("INSERT INTO facts (visitor_id, text, weight, added_at) VALUES (?,?,?,?)", (visitor_id, text, weight, time.time()))

    def set_instruction(self, scope: str, text: str) -> None:
        with closing(self._conn()) as c, c:
            c.execute("INSERT OR REPLACE INTO instructions VALUES (?,?,?)", (scope, text, time.time()))


def make_router(db_path: str = "storyteller.db", prefix: str = "/internal/storyteller", secret: str | None = None, require_signature: bool = True) -> APIRouter:
    store = Store(db_path)
    router = APIRouter(prefix=prefix)
    secret = secret if secret is not None else os.environ.get("STORYTELLER_SECRET", "")

    async def check(request: Request, body: bytes) -> None:
        if not require_signature:
            return
        if not secret:
            raise HTTPException(503, "STORYTELLER_SECRET not set")
        if not verify_signature(secret, request.headers.get("X-Storyteller-Timestamp", ""), body, request.headers.get("X-Storyteller-Signature", "")):
            raise HTTPException(401, "bad signature")

    # ---- the two consumer functions -------------------------------------------------
    @router.post("/stories")
    async def write_story(request: Request) -> dict[str, Any]:
        body = await request.body()
        await check(request, body)
        story = json.loads(body)
        if story.get("healthcheck"):
            return {"ok": True, "healthcheck": True}
        store.save_story(story)
        return {"ok": True}

    @router.get("/visitors/{visitor_id}")
    async def read_visitor(visitor_id: str, request: Request) -> Any:
        await check(request, b"")
        v = store.visitor(visitor_id)
        if v is None:
            return JSONResponse({"error": "unknown visitor"}, status_code=404)
        return v

    # ---- conveniences for you (not part of the protocol; protect them as you see fit) ---
    @router.get("/recent")
    def recent(limit: int = 50) -> list[dict[str, Any]]:
        return store.recent(limit)

    @router.post("/visitors/{visitor_id}/facts")
    def add_fact(visitor_id: str, body: dict[str, Any]) -> dict[str, bool]:
        store.add_fact(visitor_id, body["text"], body.get("weight", "normal"))
        return {"ok": True}

    @router.put("/instructions/{scope}")
    def set_instruction(scope: str, body: dict[str, Any]) -> dict[str, bool]:
        store.set_instruction(scope, body.get("text", ""))
        return {"ok": True}

    @router.get("/ui", response_class=HTMLResponse)
    def ui() -> str:
        return (Path(__file__).parent / "viewer.html").read_text().replace("__PREFIX__", prefix)

    return router
