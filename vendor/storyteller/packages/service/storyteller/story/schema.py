"""The Story: Storyteller's output contract (schema_version 1)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1"


class Outcome(BaseModel):
    label: str = Field(description="short slug, e.g. completed_signup, abandoned_signup, browsed, bounced, generation_failed")
    observed: str = Field(description="what the timeline shows about how the visit ended, no interpretation")
    inferred: str = Field(default="", description="your best reading of why, if any")
    confidence: float = Field(ge=0, le=1, default=0.5)


class Friction(BaseModel):
    at: float = Field(description="seconds into the visit where the evidence starts")
    evidence: str = Field(description="what was observed, citing timeline lines")
    inference: str = Field(description="what it probably means for the person")
    confidence: float = Field(ge=0, le=1)
    screenshot: str | None = None


class TrajectoryEntry(BaseModel):
    visit_id: str
    started_at: str
    outcome: str
    friction: list[str] = Field(default_factory=list)


class Suggestion(BaseModel):
    text: str
    confidence: float = Field(ge=0, le=1, default=0.5)


class Provenance(BaseModel):
    model: str
    prompt_version: str
    generated_at: str
    input_tokens: int = 0
    output_tokens: int = 0
    screenshots_used: int = 0
    attempts: int = 1


class LLMStory(BaseModel):
    """What the model must return. Everything else in Story is filled in by code."""

    narrative: str = Field(description="3-8 sentences, written like notes from a friend who watched over the person's shoulder")
    outcome: Outcome
    tags: list[str] = Field(default_factory=list)
    friction: list[Friction] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list, description="notable things that happened, stated plainly")
    visitor_summary: str = Field(description="1-2 sentences on what we now think is going on with this person across visits")
    suggestions: list[Suggestion] = Field(default_factory=list)


class Story(LLMStory):
    schema_version: str = SCHEMA_VERSION
    visit_id: str
    visitor_id: str
    user_id: str | None = None
    started_at: str
    ended_at: str
    duration_s: float
    entry_url: str
    referrer: str | None = None
    pages: list[str]
    device: dict[str, Any]
    consent: dict[str, Any] = Field(default_factory=lambda: {"mode": "site_start_call", "gpc": False, "opted_out": False})
    history_available: bool = False
    timeline: list[dict[str, Any]]
    timeline_text: str
    trajectory: list[TrajectoryEntry] = Field(default_factory=list)
    provenance: Provenance


def json_schema_for_llm() -> str:
    """Compact JSON schema of the fields the model must produce."""
    return json.dumps(LLMStory.model_json_schema(), indent=None)


def export_full_schema() -> dict[str, Any]:
    return Story.model_json_schema()
