"""PostConnection override — M:N with `(user_id, post_id)` unique.

Shaped so the admin's Datasette (`/admin/data/`) has a believable story
to show: connections land on posts from the last few weeks, a few
hours to a few days after each post went up (so some count toward the
3-day "good connection" window and some don't), each with 1–3
`send_post_message` audit events. Some recent posts get no connection
at all, so "Posts with no connection yet" and the "No connections"
column have rows too.

Pairs are distinct and never an author connecting to their own post
(the message route forbids that). Runs in the post-pass
(`POST_PASS_TABLES`) because posts are seeded there.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Post, PostConnection, User
from src.framework.audit.core import AuditAction
from src.framework.audit.log import AuditLog

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from . import register

# Posts older than this get no connections — the admin view only looks
# back four weeks, and older connections would just be noise.
_RECENT_DAYS = 35
_P_POST_CONNECTED = 0.85


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@register(PostConnection)
async def generate_post_connections(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[PostConnection]:
    users: list[User] = [u for u in pool.all("users") if not u.is_superuser]
    now = datetime.now(timezone.utc)
    recent: list[Post] = [
        p
        for p in pool.all("posts")
        if now - _aware(p.created_at) <= timedelta(days=_RECENT_DAYS)
    ]
    out: list[PostConnection] = []
    seen: set[tuple] = set()
    for p_index, post in enumerate(recent):
        if len(out) >= counts.POST_CONNECTION_COUNT:
            break
        if not rng.bool(_P_POST_CONNECTED):
            continue
        posted_at = _aware(post.created_at)
        for c_index in range(rng.int(1, 2)):
            sender = users[(p_index * 7 + c_index * 11) % len(users)]
            key = (sender.id, post.id)
            if sender.id == post.owner_id or key in seen:
                continue
            # Mostly inside the 3-day window; some arrive late (days 3–5).
            # Never in the future.
            delay_hours = rng.int(2, 60) if rng.bool(0.8) else rng.int(73, 120)
            made_at = min(
                posted_at + timedelta(hours=delay_hours),
                now - timedelta(minutes=30),
            )
            if made_at <= posted_at:
                continue
            seen.add(key)
            row = PostConnection(
                id=deterministic_uuid("PostConnection", len(out)),
                user_id=sender.id,
                post_id=post.id,
                created_at=made_at,
            )
            await session.merge(row)
            for m_index in range(rng.int(1, 3)):
                await session.merge(
                    AuditLog(
                        id=deterministic_uuid("PostMessage", len(out), m_index),
                        actor_id=sender.id,
                        resource_type="post_connection",
                        resource_id=row.id,
                        action=AuditAction.SEND_POST_MESSAGE.value,
                        created_at=min(made_at + timedelta(hours=m_index * 20), now),
                    )
                )
            out.append(row)
    await session.commit()
    return out
