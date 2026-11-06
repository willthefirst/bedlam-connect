"""One visit, end to end: buffer → timeline → read hook → story → write hook."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from .buffer import Buffer
from .config import Config
from .hooks import ConsumerHooks
from .llm import load_brain
from .llm.base import Brain
from .story import Story, tell_story
from .timeline import SignalConfig, TimelineConfig, build_timeline

log = logging.getLogger("storyteller.pipeline")


class Pipeline:
    def __init__(self, cfg: Config, buffer: Buffer, hooks: ConsumerHooks, brain: Brain | None = None, brief_provider: Callable[[], str] | None = None) -> None:
        self.cfg = cfg
        self.brief_provider = brief_provider or cfg.brief_text
        self.buffer = buffer
        self.hooks = hooks
        self._brain = brain
        sig = (cfg.data.get("timeline") or {}).get("signals") or {}
        self.tl_cfg = TimelineConfig(signals=SignalConfig(**{k: v for k, v in sig.items() if hasattr(SignalConfig, k)}))
        self.stories_log = Path(cfg.service.get("buffer_dir") or "./data") / "stories.jsonl"

    @property
    def brain(self) -> Brain:
        if self._brain is None:
            self._brain = load_brain(self.cfg.llm)
        return self._brain

    def story_for_recording(self, recording: dict[str, Any], consent: dict[str, Any] | None = None) -> Story:
        tl = build_timeline(recording, self.tl_cfg)
        history = self.hooks.read_visitor(tl.visitor_id) if tl.visitor_id else None
        # history None = hook unavailable/new; {} = consumer says new visitor. Either way no history.
        hist = history if history else None
        return tell_story(tl, self.brain, self.brief_provider(), hist, consent=consent)

    def deliver(self, story: Story) -> bool:
        payload = story.model_dump()
        ok = self.hooks.write_story(payload)
        if not ok:
            # always keep a local copy when delivery isn't possible, so nothing is lost
            self.stories_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.stories_log, "a") as f:
                f.write(json.dumps(payload) + "\n")
            log.info("story for visit %s appended to %s (hook %s)", story.visit_id, self.stories_log, "unconfigured" if not self.hooks.enabled else "failed")
        return ok

    def finalize_visit(self, visit_id: str) -> Story | None:
        rec = self.buffer.load(visit_id)
        if not rec.get("events"):
            self.buffer.delete(visit_id)
            return None
        try:
            story = self.story_for_recording(rec)
        except Exception:  # noqa: BLE001
            log.exception("pipeline failed for visit %s; moved to failed/", visit_id)
            self.buffer.mark_failed(visit_id)
            return None
        self.deliver(story)
        self.buffer.delete(visit_id)
        log.info("visit %s → %s (%s)", visit_id, story.outcome.label, story.provenance.model)
        return story
