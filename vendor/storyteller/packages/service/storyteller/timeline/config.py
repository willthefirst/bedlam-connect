from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SignalConfig:
    pause_s: float = 8.0  # no activity while tab visible
    hover_dwell_s: float = 3.0
    oscillation_min: int = 3  # A-B-A-B-A = 3 switches to each
    oscillation_window_s: float = 20.0
    rage_clicks: int = 3
    rage_window_s: float = 1.5
    dead_click_grace_s: float = 1.0
    back_out_s: float = 10.0
    field_stall_s: float = 6.0
    content_min_chars: int = 80
    max_screen_lines_per_mutation: int = 3


@dataclass
class TimelineConfig:
    signals: SignalConfig = field(default_factory=SignalConfig)
    render_screenshots: bool = False  # v0: off; see screenshots.py
