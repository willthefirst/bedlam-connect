from datetime import datetime, timedelta, timezone

import pytest

from src.domain.logic.admin_data import sql_functions
from src.domain.logic.admin_data.sql_functions import ago, week_label, when


def _utc_text(dt: datetime) -> str:
    return dt.replace(tzinfo=None).isoformat(sep=" ")


@pytest.fixture
def fixed_now(monkeypatch):
    """Freeze 'now' at Wed 2026-11-04 20:00 UTC (12:00 pm Pacific)."""
    now = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(sql_functions, "datetime", _Frozen)
    return now


def test_ago_counts_whole_local_days(fixed_now):
    assert ago(_utc_text(fixed_now - timedelta(hours=2))) == "Today"
    assert ago(_utc_text(fixed_now - timedelta(days=1))) == "1 day ago"
    assert ago(_utc_text(fixed_now - timedelta(days=3))) == "3 days ago"
    assert ago(None) is None


def test_ago_uses_pacific_dates(fixed_now):
    # 2026-11-04 02:00 UTC is still Nov 3 in San Francisco.
    assert ago("2026-11-04 02:00:00") == "1 day ago"


def test_when_renders_local_time():
    assert when("2026-11-02 17:00:00.123456") == "Mon Nov 2, 9:00 am"
    assert when(None) is None


def test_week_label_relative_to_current_utc_week(fixed_now):
    assert week_label("2026-11-02") == "This week"
    assert week_label("2026-10-26") == "Last week"
    assert week_label("2026-10-12") == "3 weeks ago"
