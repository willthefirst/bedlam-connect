"""Data model for the readable timeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

Kind = Literal["action", "screen", "signal", "meta"]


@dataclass
class Moment:
    t: float  # seconds since visit start
    kind: Kind
    text: str
    element: str | None = None
    url: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    screenshot: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Timeline:
    visit_id: str
    visitor_id: str
    user_id: str | None
    started_at: datetime
    ended_at: datetime
    entry_url: str
    referrer: str | None
    device: dict[str, Any]
    moments: list[Moment]
    pages: list[str]
    facts_from_site: dict[str, Any] = field(default_factory=dict)  # from identify()

    @property
    def duration_s(self) -> float:
        return round((self.ended_at - self.started_at).total_seconds(), 1)

    def render(self) -> str:
        """The human-readable block the storyteller (and humans) read."""
        lines = []
        for m in self.moments:
            stamp = f"t={_fmt_t(m.t)}"
            marker = {"signal": "  ~", "screen": "  >", "meta": "  #", "action": "   "}[m.kind]
            lines.append(f"{stamp:<9}{marker} {m.text}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "visit_id": self.visit_id,
            "visitor_id": self.visitor_id,
            "user_id": self.user_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "duration_s": self.duration_s,
            "entry_url": self.entry_url,
            "referrer": self.referrer,
            "device": self.device,
            "pages": self.pages,
            "facts_from_site": self.facts_from_site,
            "moments": [m.to_dict() for m in self.moments],
            "timeline_text": self.render(),
        }


def _fmt_t(t: float) -> str:
    if t < 60:
        return f"{t:.0f}s"
    m, s = divmod(int(round(t)), 60)
    return f"{m}m{s:02d}s"
