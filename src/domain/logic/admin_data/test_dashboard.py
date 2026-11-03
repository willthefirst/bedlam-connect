"""The "Launch health" dashboard (`plugins.datasette-dashboards` in
`metadata.yaml`).

Pins that the layout is one the plugin can render (every chart placed,
rectangular grid), that every chart's SQL runs against the migrated
schema — with and without the `weeks` filter — and that the two goal
tiles compute what their titles promise.
"""

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from datasette_dashboards import replace_opts_in_query
from sqlalchemy.orm import Session

from src.domain.logic.admin_data.datasette_app import METADATA_PATH
from src.domain.logic.admin_data.sql_functions import register_sql_functions
from src.domain.models import AdminNote, Post, PostConnection
from tests.helpers import create_test_user, make_referral_detail

_DASHBOARD = yaml.safe_load(METADATA_PATH.read_text())["plugins"][
    "datasette-dashboards"
]["launch-health"]
_CHARTS = _DASHBOARD["charts"]


def _run_chart(admin_db, slug: str, **options) -> list[dict]:
    sql = replace_opts_in_query(_CHARTS[slug]["query"], options)
    conn = sqlite3.connect(admin_db)
    register_sql_functions(conn)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, options)]
    finally:
        conn.close()


def test_layout_is_a_full_rectangular_grid():
    rows = _DASHBOARD["layout"]
    assert len({len(row) for row in rows}) == 1, "every row needs the same width"
    placed = {slot for row in rows for slot in row} - {"."}
    assert placed == set(_CHARTS), "every chart must be placed, and only charts"


def test_no_filter_declares_a_default():
    """A `default:` makes datasette-dashboards redirect bare visits and
    copy every request cookie onto the redirect with Datasette's
    `set_cookie` — reissuing our session cookie without HttpOnly/Secure.
    See the comment on `filters:` in `metadata.yaml`."""
    for name, spec in _DASHBOARD.get("filters", {}).items():
        assert "default" not in spec, f"filter {name!r} must not set a default"


@pytest.mark.parametrize("slug", sorted(_CHARTS))
@pytest.mark.parametrize("options", [{}, {"weeks": "8"}], ids=["no-filter", "weeks"])
def test_every_chart_query_runs(admin_db, slug, options):
    rows = _run_chart(admin_db, slug, **options)
    chart = _CHARTS[slug]
    if chart["library"] == "metric":
        assert len(rows) == 1
        assert chart["display"]["field"] in rows[0]


def _monday(weeks_back: int) -> datetime:
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday() + 7 * weeks_back)
    return datetime(monday.year, monday.month, monday.day, 12)


def _good_post(orm: Session, *, posted: datetime, good: bool) -> None:
    author = create_test_user(username=f"a-{uuid.uuid4()}")
    sender = create_test_user(username=f"s-{uuid.uuid4()}")
    post = Post(kind="referral", owner_id=author.id, created_at=posted)
    post.referral_detail = make_referral_detail()
    orm.add_all([author, sender, post])
    orm.flush()
    connection = PostConnection(
        user_id=sender.id, post_id=post.id, created_at=posted + timedelta(hours=2)
    )
    orm.add(connection)
    orm.flush()
    orm.add(
        AdminNote(
            subject_type="connection",
            subject_id=connection.id,
            action="verdict",
            value="good" if good else "not_good",
        )
    )


def test_goal_tiles(admin_db, orm):
    # Last week: 3 of 4 decided posts good (75%, on goal).
    # Two weeks ago: 1 of 2 (50%, below) — so the streak is exactly 1.
    for good in (True, True, True, False):
        _good_post(orm, posted=_monday(1) + timedelta(days=1), good=good)
    for good in (True, False):
        _good_post(orm, posted=_monday(2) + timedelta(days=1), good=good)
    orm.commit()

    assert _run_chart(admin_db, "share-last-week") == [{"share": 75}]
    assert _run_chart(admin_db, "goal-streak") == [{"streak": 1}]


def test_goal_streak_is_zero_with_no_history(admin_db):
    assert _run_chart(admin_db, "goal-streak") == [{"streak": 0}]
    assert _run_chart(admin_db, "share-last-week") == [{"share": 0}]
