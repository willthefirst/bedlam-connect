"""FastAPI app: the snippet-facing and admin routes, plus the finalizer loop."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .buffer import Buffer
from .config import Config, load_config
from .hooks import ConsumerHooks
from .pipeline import Pipeline
from .timeline import build_timeline

log = logging.getLogger("storyteller")


class State:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        data_dir = Path(cfg.service.get("buffer_dir") or "./data")
        if not data_dir.is_absolute():
            data_dir = cfg.base_dir / data_dir
        self.data_dir = data_dir
        self.buffer = Buffer(data_dir)
        self.hooks = ConsumerHooks(cfg.consumer, cfg.secret())
        self._file_brief = cfg.brief_text  # the brief from the config file
        self.pipeline = Pipeline(cfg, self.buffer, self.hooks, brief_provider=self.brief)
        self.flag_file = data_dir / "recording.json"
        self.brief_file = data_dir / "brief.md"
        self.hook_status: dict[str, Any] = {}
        self.started = time.time()
        self.finalized = 0

    def recording_enabled(self) -> bool:
        if self.flag_file.exists():
            try:
                return bool(json.loads(self.flag_file.read_text()).get("enabled"))
            except Exception:  # noqa: BLE001
                pass
        return bool(self.cfg.recording.get("default_enabled", False))

    def set_recording(self, enabled: bool) -> None:
        self.flag_file.write_text(json.dumps({"enabled": enabled, "changed_at": time.time()}))

    def brief(self) -> str:
        return self.brief_file.read_text() if self.brief_file.exists() else self._file_brief()


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    st = State(cfg)
    prefix = (cfg.service.get("prefix") or "/storyteller").rstrip("/")
    app = FastAPI(title="Storyteller", version="0.1.0")
    app.state.st = st
    origins = cfg.site.get("allowed_origins") or ["*"]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    def admin(authorization: str = Header(default="")) -> None:
        token = cfg.admin_token()
        if not token:
            raise HTTPException(503, "admin token not configured (STORYTELLER_ADMIN_TOKEN)")
        if authorization != f"Bearer {token}":
            raise HTTPException(401, "bad admin token")

    @app.get(prefix + "/recording")
    def get_recording() -> dict[str, bool]:
        return {"enabled": st.recording_enabled()}

    @app.post(prefix + "/recording", dependencies=[Depends(admin)])
    def set_recording(body: dict[str, Any]) -> dict[str, bool]:
        st.set_recording(bool(body.get("enabled")))
        return {"enabled": st.recording_enabled()}

    @app.post(prefix + "/events", status_code=204)
    async def events(request: Request) -> Response:
        if not st.recording_enabled():
            return JSONResponse({"error": "recording disabled"}, status_code=403)
        try:
            chunk = json.loads(await request.body())
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "bad json")
        site_key = cfg.site.get("key") or ""
        if site_key and chunk.get("siteKey") != site_key:
            raise HTTPException(403, "bad site key")
        if not chunk.get("visitId") or not isinstance(chunk.get("events"), list):
            raise HTTPException(400, "visitId and events required")
        if len(chunk["events"]) > 5000:
            raise HTTPException(413, "too many events in one chunk")
        st.buffer.append(chunk)
        return Response(status_code=204)

    @app.get(prefix + "/brief", dependencies=[Depends(admin)])
    def get_brief() -> dict[str, str]:
        return {"brief": st.brief()}

    @app.put(prefix + "/brief", dependencies=[Depends(admin)])
    async def put_brief(request: Request) -> dict[str, str]:
        text = (await request.body()).decode()
        st.brief_file.write_text(text)
        return {"brief": text}

    @app.post(prefix + "/visits/{visit_id}/regenerate", dependencies=[Depends(admin)])
    def regenerate(visit_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Body: {"recording": {...}} (raw events) or {"timeline": {...}} (a Timeline dict) plus optional "history"."""
        from .story import tell_story
        from .timeline.model import Moment, Timeline
        from datetime import datetime

        history = body.get("history")
        if body.get("recording"):
            tl = build_timeline(body["recording"], st.pipeline.tl_cfg)
        elif body.get("timeline"):
            d = body["timeline"]
            tl = Timeline(
                visit_id=d.get("visit_id", visit_id), visitor_id=d.get("visitor_id", ""), user_id=d.get("user_id"),
                started_at=datetime.fromisoformat(d["started_at"]), ended_at=datetime.fromisoformat(d["ended_at"]),
                entry_url=d.get("entry_url", "/"), referrer=d.get("referrer"), device=d.get("device") or {},
                moments=[Moment(**{k: m.get(k) for k in ("t", "kind", "text", "element", "url", "evidence", "screenshot")}) for m in d.get("moments") or d.get("timeline") or []],
                pages=d.get("pages") or [], facts_from_site=d.get("facts_from_site") or {},
            )
        else:
            raise HTTPException(400, "recording or timeline required")
        if history is None and tl.visitor_id:
            history = st.hooks.read_visitor(tl.visitor_id) or None
        story = tell_story(tl, st.pipeline.brain, st.brief(), history)
        delivered = st.pipeline.deliver(story) if body.get("deliver", True) else False
        return {"delivered": delivered, "story": story.model_dump()}

    @app.get(prefix + "/health")
    def health() -> dict[str, Any]:
        llm = cfg.llm
        return {
            "ok": bool(st.hook_status.get("ok")) or not st.hooks.enabled,
            "recording_enabled": st.recording_enabled(),
            "active_visits": st.buffer.count_active(),
            "finalized_since_start": st.finalized,
            "uptime_s": int(time.time() - st.started),
            "llm": {"provider": llm.get("provider"), "model": llm.get("model"), "base_url": llm.get("base_url")},
            "consumer": {"base_url": cfg.consumer.get("base_url"), "routes": cfg.consumer.get("routes"), "check": st.hook_status},
            "brief_chars": len(st.brief()),
            "idle_timeout_minutes": cfg.recording.get("idle_timeout_minutes"),
        }

    async def finalizer() -> None:
        idle_s = float(cfg.recording.get("idle_timeout_minutes", 10)) * 60
        every = float(cfg.service.get("finalize_every_seconds", 30))
        while True:
            try:
                ended = [v for v in list(st.buffer.active.glob("*.jsonl")) if st.buffer.has_visit_end(v.stem) and time.time() - v.stat().st_mtime > 5]
                idle = list(st.buffer.idle_visits(idle_s))
                for visit_id in {*(v.stem for v in ended), *idle}:
                    story = await asyncio.to_thread(st.pipeline.finalize_visit, visit_id)
                    if story is not None:
                        st.finalized += 1
            except Exception:  # noqa: BLE001
                log.exception("finalizer loop error")
            await asyncio.sleep(every)

    @app.on_event("startup")
    async def _startup() -> None:
        st.hook_status = await asyncio.to_thread(st.hooks.startup_check)
        log.info("storyteller up: prefix=%s recording=%s hooks=%s", prefix, st.recording_enabled(), st.hook_status)
        asyncio.create_task(finalizer())

    return app
