"""On-disk per-visit buffer. One JSONL file per visit: first line is meta, then event chunks."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Iterator

_SAFE = re.compile(r"[^A-Za-z0-9_-]")


class Buffer:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.active = self.root / "active"
        self.failed = self.root / "failed"
        self.active.mkdir(parents=True, exist_ok=True)
        self.failed.mkdir(parents=True, exist_ok=True)

    def _path(self, visit_id: str) -> Path:
        return self.active / (_SAFE.sub("_", visit_id)[:80] + ".jsonl")

    def append(self, chunk: dict[str, Any]) -> None:
        p = self._path(chunk["visitId"])
        new = not p.exists()
        with open(p, "a") as f:
            if new:
                f.write(json.dumps({"_meta": True, "visitorId": chunk.get("visitorId"), "visitId": chunk["visitId"], "siteKey": chunk.get("siteKey")}) + "\n")
            f.write(json.dumps({"userId": chunk.get("userId"), "seq": chunk.get("seq"), "events": chunk.get("events") or []}) + "\n")

    def last_event_ms(self, visit_id: str) -> float | None:
        p = self._path(visit_id)
        return p.stat().st_mtime * 1000 if p.exists() else None

    def idle_visits(self, idle_seconds: float) -> Iterator[str]:
        now = time.time()
        for p in self.active.glob("*.jsonl"):
            if now - p.stat().st_mtime >= idle_seconds:
                yield p.stem

    def has_visit_end(self, visit_id: str) -> bool:
        p = self._path(visit_id)
        if not p.exists():
            return False
        with open(p) as f:
            tail = f.read()[-4000:]
        return '"visit_end"' in tail

    def load(self, visit_id: str) -> dict[str, Any]:
        p = self._path(visit_id)
        meta: dict[str, Any] = {}
        events: list[dict[str, Any]] = []
        user_id = None
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                if d.get("_meta"):
                    meta = d
                    continue
                user_id = d.get("userId") or user_id
                events.extend(d.get("events") or [])
        events.sort(key=lambda e: e["timestamp"])
        return {"visitorId": meta.get("visitorId"), "visitId": meta.get("visitId") or visit_id, "siteKey": meta.get("siteKey"), "userId": user_id, "events": events}

    def delete(self, visit_id: str) -> None:
        p = self._path(visit_id)
        if p.exists():
            os.remove(p)

    def mark_failed(self, visit_id: str) -> None:
        p = self._path(visit_id)
        if p.exists():
            shutil.move(str(p), str(self.failed / p.name))

    def count_active(self) -> int:
        return sum(1 for _ in self.active.glob("*.jsonl"))
