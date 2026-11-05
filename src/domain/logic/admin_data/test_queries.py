"""Behavior of the saved queries in `metadata.yaml`, run as raw SQL
against a migrated DB (see `conftest.py`).

Pins what each query is for: daily queries list exactly the cases to
act on and drop them once the matching note is logged; `post_outcomes`
buckets posts per the spec's shared definition; weekly health counts
those buckets; timelines tell one post's or person's story; and the
one write (`add_note`) normalizes input and is held to the
`admin_notes` CHECKs.
"""

import sqlite3
import uuid

import pytest
from sqlalchemy.orm import Session

from src.domain.logic.admin_data.sql_functions import ago, register_sql_functions
from src.domain.models import AdminNote, Post, PostConnection, User
from src.framework.audit.core import AuditAction
from src.framework.audit.log import AuditLog
from tests.helpers import create_test_user, make_clinician, make_referral_detail

from .conftest import days_ago

# Daily queries are worked top to bottom; each row ends with the ID the
# admin pastes into "Add a note" or a timeline.
_DAILY = (
    "new_connections",
    "check_ins_due",
    "posts_without_connections",
    "members_not_started",
)


def _member(orm: Session, first: str, last: str, **user_kwargs) -> User:
    user = create_test_user(username=f"{first.lower()}-{uuid.uuid4()}", **user_kwargs)
    user.created_at = days_ago(30)
    orm.add(user)
    orm.add(
        make_clinician(
            owner_id=user.id, first_name=first, last_name=last, clinician_verified=True
        )
    )
    return user


def _post(orm: Session, owner: User, *, age_days: float) -> Post:
    post = Post(kind="referral", owner_id=owner.id, created_at=days_ago(age_days))
    post.referral_detail = make_referral_detail(
        age_groups=["adults_25_64"], insurance_carriers=["kaiser"]
    )
    orm.add(post)
    orm.flush()  # assigns post.id
    return post


def _connect(
    orm: Session, sender: User, post: Post, *, age_days: float, messages: int = 1
) -> PostConnection:
    connection = PostConnection(
        user_id=sender.id, post_id=post.id, created_at=days_ago(age_days)
    )
    orm.add(connection)
    orm.flush()
    for _ in range(messages):
        orm.add(
            AuditLog(
                actor_id=sender.id,
                resource_type="post_connection",
                resource_id=connection.id,
                action=AuditAction.SEND_POST_MESSAGE.value,
                created_at=days_ago(age_days),
            )
        )
    return connection


@pytest.fixture
def scenario(orm: Session):
    """Dana posts; Elena reaches out on one post (twice)."""
    author = _member(orm, "Dana", "Ortiz")
    sender = _member(orm, "Elena", "Fischer")
    connected = _post(orm, author, age_days=5)
    quiet = _post(orm, author, age_days=2)
    fresh = _post(orm, author, age_days=0.2)
    connection = _connect(orm, sender, connected, age_days=4.5, messages=2)
    orm.commit()
    return {
        "author": author,
        "sender": sender,
        "connected": connected,
        "quiet": quiet,
        "fresh": fresh,
        "connection": connection,
        "admin": None,
    }


def _note(run_query, subject_type, subject, action, value="", note="", actor=None):
    return run_query(
        "add_note",
        _random_chars_32=uuid.uuid4().hex,
        _actor_id=actor.id.hex if actor else None,
        subject_type=subject_type,
        subject_id=str(subject.id),
        action=action,
        value=value,
        note=note,
    )


def test_new_connections_lists_unreviewed_until_reviewed(scenario, run_query):
    rows = run_query("new_connections")
    # `ago` counts whole Pacific calendar days, so a 4.5-day-old row reads
    # "4 days ago" in the afternoon but "5 days ago" before noon. The
    # rendering itself is pinned under a frozen clock in
    # `test_sql_functions.py`; here we only pin that the query uses it.
    assert rows == [
        {
            "connection": "Elena Fischer → Dana Ortiz",
            "on_post": "Referral: adults_25_64, kaiser",
            "made": ago(str(scenario["connection"].created_at)),
            "messages": 2,
            "id": scenario["connection"].id.hex,
        }
    ]

    _note(run_query, "connection", scenario["connection"], "reviewed")
    assert run_query("new_connections") == []


def test_check_ins_due_until_check_in_sent(scenario, run_query, orm):
    young = _connect(orm, scenario["sender"], scenario["quiet"], age_days=1)
    orm.commit()

    rows = run_query("check_ins_due")
    assert [r["id"] for r in rows] == [scenario["connection"].id.hex]
    assert young.id.hex not in {r["id"] for r in rows}
    assert rows[0]["post_author"].startswith("Dana Ortiz, ")

    _note(run_query, "connection", scenario["connection"], "check_in_sent")
    assert run_query("check_ins_due") == []


def test_posts_without_connections_skips_new_and_connected(scenario, run_query):
    rows = run_query("posts_without_connections")
    assert [r["id"] for r in rows] == [scenario["quiet"].id.hex]

    _note(run_query, "post", scenario["quiet"], "reviewed")
    assert run_query("posts_without_connections") == []


def test_members_not_started(scenario, run_query, orm):
    unverified = create_test_user(username="unverified", is_verified=False)
    idle = _member(orm, "Idle", "Member")
    admin = create_test_user(username="admin", is_superuser=True, is_verified=False)
    orm.add_all([unverified, admin])
    orm.commit()

    rows = {r["id"]: r["stuck_at"] for r in run_query("members_not_started")}
    assert rows == {
        unverified.id.hex: "Email not verified",
        idle.id.hex: "Onboarded, no post or reach-out",
    }

    _note(run_query, "member", idle, "reviewed")
    assert idle.id.hex not in {r["id"] for r in run_query("members_not_started")}


def test_add_note_normalizes_and_stamps_author(scenario, run_query, orm):
    _note(
        run_query,
        "Connection",
        scenario["connection"],
        "verdict",
        value="Not Good",
        note=" Client had Blue Shield. ",
        actor=scenario["author"],
    )

    note = orm.query(AdminNote).one()
    assert note.subject_type == "connection"
    assert note.subject_id == scenario["connection"].id
    assert note.value == "not_good"
    assert note.note == "Client had Blue Shield."
    assert note.author_id == scenario["author"].id
    assert note.created_at is not None


@pytest.mark.parametrize(
    "action, value",
    [
        ("verdict", "maybe"),
        ("check_in_reply", "good"),
        ("reviewed", "good"),
        ("emailed", ""),
    ],
)
def test_add_note_rejects_values_outside_the_checks(scenario, run_query, action, value):
    with pytest.raises(sqlite3.IntegrityError):
        _note(run_query, "connection", scenario["connection"], action, value=value)


def test_post_outcomes_follow_the_shared_definition(scenario, run_query, orm, admin_db):
    old = _post(orm, scenario["author"], age_days=10)
    late = _post(orm, scenario["author"], age_days=10)
    # Connected, but only after the 3-day window: still "none".
    _connect(orm, scenario["sender"], late, age_days=5)
    orm.commit()

    def outcomes() -> dict[str, str]:
        with sqlite3.connect(admin_db) as conn:
            return dict(conn.execute("select post_id, outcome from post_outcomes"))

    assert outcomes() == {
        scenario["connected"].id.hex: "waiting",  # connected, no verdict yet
        scenario["quiet"].id.hex: "waiting",  # too new to call
        scenario["fresh"].id.hex: "waiting",
        old.id.hex: "none",
        late.id.hex: "none",
    }

    _note(run_query, "connection", scenario["connection"], "verdict", value="not_good")
    assert outcomes()[scenario["connected"].id.hex] == "not_fit"

    # The latest verdict wins.
    _note(run_query, "connection", scenario["connection"], "verdict", value="good")
    assert outcomes()[scenario["connected"].id.hex] == "good"


def test_weekly_health_counts_outcomes(scenario, run_query):
    _note(run_query, "connection", scenario["connection"], "verdict", value="good")

    rows = run_query("weekly_health")
    totals = {
        key: sum(r[key] for r in rows)
        for key in ("good", "not_a_fit", "no_connections", "waiting")
    }
    assert totals == {"good": 1, "not_a_fit": 0, "no_connections": 0, "waiting": 2}
    connected_week = next(r for r in rows if r["good"] == 1)
    assert connected_week["share_good"] == "100%, on goal"


def test_posts_by_outcome_drills_into_a_week(scenario, run_query, admin_db):
    _note(
        run_query,
        "connection",
        scenario["connection"],
        "verdict",
        value="good",
        note="Booked an intake",
    )
    with sqlite3.connect(admin_db) as conn:
        (week,) = conn.execute(
            "select week_posted from post_outcomes where post_id = ?",
            (scenario["connected"].id.hex,),
        ).fetchone()

    rows = run_query("posts_by_outcome", week=f"{week} · whatever", outcome="Good")
    assert len(rows) == 1
    assert rows[0]["id"] == scenario["connected"].id.hex
    assert rows[0]["connections"] == 1
    assert rows[0]["latest_note"] == "good: Booked an intake"


def test_post_timeline_tells_the_story(scenario, run_query):
    _note(
        run_query,
        "connection",
        scenario["connection"],
        "check_in_sent",
        actor=scenario["author"],
    )
    rows = run_query("post_timeline", post_id=str(scenario["connected"].id))
    assert [(r["what_happened"], r["who"]) for r in rows] == [
        ("Posted", "Dana Ortiz"),
        ("Connection", "Elena Fischer"),
        ("Message sent", "Elena Fischer"),
        ("Message sent", "Elena Fischer"),
        ("Check-in sent", "Dana Ortiz"),
    ]


def test_member_timeline_tells_the_story(scenario, run_query):
    rows = run_query("member_timeline", member_id=scenario["sender"].id.hex)
    whats = [r["what_happened"] for r in rows]
    assert whats[0] == "Signed up"
    assert "Reached out: Referral: adults_25_64, kaiser" in whats
    assert whats.count("Message sent: Referral: adults_25_64, kaiser") == 2


def test_result_shape_follows_the_reading_rules(admin_db, run_query):
    """Six columns at most; daily queries end in the row's ID. Read off
    the cursor description, so it holds even for empty results."""
    params = {"week": "2026-01-05", "outcome": "good", "post_id": "", "member_id": ""}
    conn = sqlite3.connect(admin_db)
    register_sql_functions(conn)
    try:
        for name, query in run_query.queries.items():
            if query.get("write"):
                continue
            cursor = conn.execute(query["sql"], params)
            columns = [d[0] for d in cursor.description]
            assert len(columns) <= 6, f"{name} returns {len(columns)} columns"
            if name in _DAILY:
                assert columns[-1] == "id", f"{name} should end with the row's id"
    finally:
        conn.close()
