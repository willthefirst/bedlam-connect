"""Timeline + brief + history → Story, with validation and one retry."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from ..llm.base import Brain, Image, Message
from ..timeline.model import Timeline
from .prompt import PROMPT_VERSION, build_messages, parse_brief
from .schema import LLMStory, Outcome, Provenance, Story, TrajectoryEntry

log = logging.getLogger("storyteller.story")


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def tell_story(
    tl: Timeline,
    brain: Brain,
    brief_text: str,
    history: dict[str, Any] | None = None,
    images: list[Image] | None = None,
    consent: dict[str, Any] | None = None,
) -> Story:
    brief, tags, site_instructions = parse_brief(brief_text)
    system, user = build_messages(tl, brief, tags, history, site_instructions)
    messages = [Message("user", user)]
    imgs = images if (images and brain.supports_images) else None

    attempts = 0
    llm_story: LLMStory | None = None
    in_tok = out_tok = 0
    model = getattr(brain, "model", getattr(brain, "name", "unknown"))
    last_err = ""
    while attempts < 2 and llm_story is None:
        attempts += 1
        comp = brain.complete(system, messages, imgs, json=True)
        in_tok += comp.input_tokens
        out_tok += comp.output_tokens
        model = comp.model or model
        try:
            llm_story = LLMStory.model_validate(_extract_json(comp.text))
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            last_err = str(e)[:1500]
            log.warning("story validation failed (attempt %d): %s", attempts, last_err)
            messages = [Message("user", user), Message("assistant", comp.text), Message("user", f"That was not valid against the schema:\n{last_err}\nReturn the corrected JSON object only.")]

    if llm_story is None:
        llm_story = LLMStory(
            narrative=f"Story generation failed after {attempts} attempts: {last_err[:300]}",
            outcome=Outcome(label="generation_failed", observed=f"visit of {tl.duration_s}s over {len(tl.pages)} page(s)", confidence=0.0),
            visitor_summary="",
        )

    trajectory = [TrajectoryEntry.model_validate(t) for t in (history or {}).get("trajectory") or []][-19:]
    trajectory.append(
        TrajectoryEntry(
            visit_id=tl.visit_id,
            started_at=tl.started_at.isoformat(timespec="seconds"),
            outcome=llm_story.outcome.label,
            friction=[f.inference[:80] for f in llm_story.friction],
        )
    )
    return Story(
        **llm_story.model_dump(),
        visit_id=tl.visit_id,
        visitor_id=tl.visitor_id,
        user_id=tl.user_id,
        started_at=tl.started_at.isoformat(timespec="seconds"),
        ended_at=tl.ended_at.isoformat(timespec="seconds"),
        duration_s=tl.duration_s,
        entry_url=tl.entry_url,
        referrer=tl.referrer,
        pages=tl.pages,
        device=tl.device,
        consent=consent or {"mode": "site_start_call", "gpc": False, "opted_out": False},
        history_available=history is not None,
        timeline=[m.to_dict() for m in tl.moments],
        timeline_text=tl.render(),
        trajectory=trajectory,
        provenance=Provenance(
            model=str(model),
            prompt_version=PROMPT_VERSION,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            input_tokens=in_tok,
            output_tokens=out_tok,
            screenshots_used=len(imgs or []),
            attempts=attempts,
        ),
    )
