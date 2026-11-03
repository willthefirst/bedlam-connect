"""Display helpers registered as SQLite functions on Datasette's
connections, so the saved queries in `metadata.yaml` read "3 days ago"
instead of raw UTC timestamps.

Stored timestamps are naive UTC text (`YYYY-MM-DD HH:MM:SS[.ffffff]`);
the helpers render them in the admin's local time (`DISPLAY_TZ`) so
"today" means the admin's today. Pure functions — the query tests call
`register_sql_functions` on a plain `sqlite3` connection to run the
same SQL Datasette runs.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("America/Los_Angeles")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace(" ", "T"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(DISPLAY_TZ)


def _today() -> date:
    return datetime.now(DISPLAY_TZ).date()


def ago(value: str | None) -> str | None:
    """'Today', '1 day ago', '3 days ago' — whole local days."""
    parsed = _parse(value)
    if parsed is None:
        return None
    days = (_today() - parsed.date()).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"


def when(value: str | None) -> str | None:
    """'Mon Nov 2, 9:00 am' — for timelines, where order within a day
    matters."""
    parsed = _parse(value)
    if parsed is None:
        return None
    hour = parsed.strftime("%I").lstrip("0")
    return f"{parsed:%a %b} {parsed.day}, {hour}:{parsed:%M} {parsed:%p}".replace(
        "AM", "am"
    ).replace("PM", "pm")


def week_label(value: str | None) -> str | None:
    """Label a week-start date (`YYYY-MM-DD`, a Monday) relative to the
    current UTC week: 'This week', 'Last week', '3 weeks ago'. Weeks
    are bucketed in UTC by the views, so this compares in UTC too."""
    if not value:
        return None
    week = date.fromisoformat(str(value)[:10])
    today = datetime.now(timezone.utc).date()
    this_week = date.fromordinal(today.toordinal() - today.weekday())
    weeks = (this_week - week).days // 7
    if weeks <= 0:
        return "This week"
    if weeks == 1:
        return "Last week"
    return f"{weeks} weeks ago"


def register_sql_functions(conn: sqlite3.Connection) -> None:
    for name, fn in (("ago", ago), ("when_at", when), ("week_label", week_label)):
        conn.create_function(name, 1, fn, deterministic=False)
