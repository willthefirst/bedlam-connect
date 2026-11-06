"""Consumer-side pieces of the Storyteller protocol: signature check + store.

Adapted from the library's reference FastAPI adapter
(`vendor/storyteller/packages/adapters/fastapi/storyteller_adapter.py`).
The route functions moved to `src/domain/routes/storyteller.py` so the
viewer and its conveniences can sit behind the app's normal
`current_admin_user` dependency; the protocol pieces (the HMAC check and
the SQLite store the stories land in) live here. See the README next to
this file for what changed and why.

The store is a SQLite file of its own, *not* a table in the app DB: the
library's contract is that stories are plain rows the consumer owns and
can query however it likes, and keeping them out of the ORM/Alembic world
means the story schema (which the library versions) can change without
an app migration. `stories.story` holds the full Story JSON.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
  visit_id TEXT PRIMARY KEY, visitor_id TEXT, user_id TEXT, started_at TEXT,
  outcome TEXT, narrative TEXT, tags TEXT, story JSON, received_at REAL
);
CREATE INDEX IF NOT EXISTS stories_visitor ON stories(visitor_id, started_at);
CREATE TABLE IF NOT EXISTS visitors (
  visitor_id TEXT PRIMARY KEY, user_id TEXT, summary TEXT, trajectory JSON,
  updated_at REAL
);
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, visitor_id TEXT, text TEXT,
  weight TEXT DEFAULT 'normal', added_at REAL
);
CREATE TABLE IF NOT EXISTS instructions (
  scope TEXT PRIMARY KEY, text TEXT, updated_at REAL
);
"""

# Header names the service signs every hook request with. Protocol:
# `vendor/storyteller/docs/protocol.md § Signing`.
TIMESTAMP_HEADER = "X-Storyteller-Timestamp"
SIGNATURE_HEADER = "X-Storyteller-Signature"
MAX_SKEW_SECONDS = 300


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """`v1=<hex hmac_sha256(secret, "<timestamp>.<raw body>")>`."""
    digest = hmac.new(
        secret.encode(), f"{timestamp}.{body.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    return f"v1={digest}"


def verify_signature(
    secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    *,
    max_skew: int = MAX_SKEW_SECONDS,
    now: float | None = None,
) -> bool:
    """True iff `signature` matches `body` under `secret` and the timestamp
    is within `max_skew` seconds of now (replay window)."""
    try:
        if abs((now if now is not None else time.time()) - int(timestamp)) > max_skew:
            return False
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature or "")


class Store:
    """The stories/visitors/facts/instructions tables in one SQLite file.

    Schema creation is lazy (first use) and the parent directory is
    created on demand, so importing the module or building the app never
    touches disk — only a hook delivery or an admin page view does.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._ready = False

    def _conn(self) -> sqlite3.Connection:
        if not self._ready:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path)) as c:
                c.executescript(SCHEMA)
            self._ready = True
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def save_story(self, s: dict[str, Any]) -> None:
        with closing(self._conn()) as c, c:
            c.execute(
                "INSERT OR REPLACE INTO stories VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    s["visit_id"],
                    s.get("visitor_id"),
                    s.get("user_id"),
                    s.get("started_at"),
                    (s.get("outcome") or {}).get("label"),
                    s.get("narrative"),
                    json.dumps(s.get("tags") or []),
                    json.dumps(s),
                    time.time(),
                ),
            )
            c.execute(
                "INSERT OR REPLACE INTO visitors VALUES (?,?,?,?,?)",
                (
                    s.get("visitor_id"),
                    s.get("user_id"),
                    s.get("visitor_summary"),
                    json.dumps(s.get("trajectory") or []),
                    time.time(),
                ),
            )

    def visitor(self, visitor_id: str) -> dict[str, Any] | None:
        """The read-hook response for `visitor_id`, or None if we know
        nothing about them (→ 404, which the service treats as "new")."""
        with closing(self._conn()) as c:
            v = c.execute(
                "SELECT * FROM visitors WHERE visitor_id=?", (visitor_id,)
            ).fetchone()
            facts = c.execute(
                "SELECT text, weight, added_at FROM facts"
                " WHERE visitor_id=? ORDER BY added_at",
                (visitor_id,),
            ).fetchall()
            ins = {
                r["scope"]: r["text"]
                for r in c.execute("SELECT scope, text FROM instructions").fetchall()
            }
        visitor_scope = f"visitor:{visitor_id}"
        if v is None and not facts and not ins.get(visitor_scope):
            return None
        return {
            "schema_version": "1",
            "summary": v["summary"] if v else "",
            "trajectory": json.loads(v["trajectory"]) if v else [],
            "facts": [
                {"text": f["text"], "weight": f["weight"], "added_at": f["added_at"]}
                for f in facts
            ],
            "instructions": {
                "global": ins.get("global", ""),
                "visitor": ins.get(visitor_scope, ""),
            },
        }

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with closing(self._conn()) as c:
            rows = c.execute(
                "SELECT story FROM stories ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(r["story"]) for r in rows]

    def add_fact(self, visitor_id: str, text: str, weight: str = "normal") -> None:
        with closing(self._conn()) as c, c:
            c.execute(
                "INSERT INTO facts (visitor_id, text, weight, added_at)"
                " VALUES (?,?,?,?)",
                (visitor_id, text, weight, time.time()),
            )

    def set_instruction(self, scope: str, text: str) -> None:
        with closing(self._conn()) as c, c:
            c.execute(
                "INSERT OR REPLACE INTO instructions VALUES (?,?,?)",
                (scope, text, time.time()),
            )
