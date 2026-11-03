"""AdminNote override — the admin's observability trail, for demoing
`/admin/data/`.

Walks the seeded connections oldest-first and plays out the daily
routine from the Observability spec: most get reviewed; those 2+ days
old usually get a check-in, and most check-ins get a reply and a good /
not-good verdict. Newer connections stay un-noted, so the daily queries
("New connections", "Check-ins due") still have rows to act on. A few
quiet posts and members get a "reviewed" note too. Notes are authored by the seeded
admin.

Values satisfy the `admin_notes` CHECKs by construction. Runs in the
post-pass after `post_connections`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import AdminNote, PostConnection, User

from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from . import register

_GOOD_NOTES = (
    "Booked an intake for next week.",
    "Client started with them.",
    "Good fit — same insurance and location.",
)
_NOT_GOOD_NOTES = (
    "Client had Blue Shield.",
    "No openings by the time they replied.",
    "Wanted in-person; provider is telehealth only.",
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@register(AdminNote)
async def generate_admin_notes(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[AdminNote]:
    users: list[User] = pool.all("users")
    admin = next((u for u in users if u.is_superuser), None)
    connections: list[PostConnection] = sorted(
        pool.all("post_connections"), key=lambda c: _aware(c.created_at)
    )
    now = datetime.now(timezone.utc)
    out: list[AdminNote] = []

    def note(subject_type, subject_id, action, at, value=None, text=None) -> None:
        row = AdminNote(
            id=deterministic_uuid("AdminNote", len(out)),
            subject_type=subject_type,
            subject_id=subject_id,
            action=action,
            value=value,
            note=text,
            author_id=admin.id if admin else None,
            created_at=min(at, now),
        )
        out.append(row)

    for connection in connections:
        made_at = _aware(connection.created_at)
        age = now - made_at
        # Leave the newest connections for the admin to work through.
        if age < timedelta(days=1) or not rng.bool(0.8):
            continue
        note("connection", connection.id, "reviewed", made_at + timedelta(hours=3))
        if age < timedelta(days=2) or not rng.bool(0.85):
            continue
        sent_at = made_at + timedelta(days=2)
        note("connection", connection.id, "check_in_sent", sent_at)
        if age < timedelta(days=3) or not rng.bool(0.8):
            continue
        good = rng.bool(0.7)
        reply = "yes" if good else rng.choice(("no", "not_yet"))
        note(
            "connection",
            connection.id,
            "check_in_reply",
            sent_at + timedelta(hours=6),
            reply,
        )
        note(
            "connection",
            connection.id,
            "verdict",
            sent_at + timedelta(hours=7),
            "good" if good else "not_good",
            rng.choice(_GOOD_NOTES if good else _NOT_GOOD_NOTES),
        )

    connected_posts = {c.post_id for c in connections}
    quiet_posts = [p for p in pool.all("posts") if p.id not in connected_posts]
    for post in quiet_posts[:3]:
        note(
            "post",
            post.id,
            "reviewed",
            now - timedelta(days=1),
            text="Asked the author to add insurance details.",
        )

    # The last seeded users, not the first: the first slots are the
    # not-yet-onboarded personas, which "Members who haven't started"
    # should keep showing.
    for member in [u for u in users if not u.is_superuser][-2:]:
        note(
            "member",
            member.id,
            "reviewed",
            now - timedelta(days=1),
            text="Emailed to help them finish setup.",
        )

    for row in out:
        await session.merge(row)
    await session.commit()
    return out
