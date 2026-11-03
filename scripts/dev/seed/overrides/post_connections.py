"""PostConnection override — M:N with `(user_id, post_id)` unique.

Generic generator would pick random pairs and could violate the
UNIQUE constraint on collision, and could connect an author to their
own post (the message route forbids that). This override generates
distinct, non-self pairs by indexing (user, post) with co-prime
strides. Runs in the post-pass (`POST_PASS_TABLES`) because posts are
seeded there.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Post, PostConnection, User

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from . import register


@register(PostConnection)
async def generate_post_connections(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[PostConnection]:
    users: list[User] = pool.all("users")
    posts: list[Post] = pool.all("posts")
    seen: set[tuple] = set()
    out: list[PostConnection] = []
    target = min(counts.POST_CONNECTION_COUNT, len(users) * len(posts))
    i = 0
    while len(out) < target and i < target * 4:
        u = users[(i * 7) % len(users)]
        p = posts[(i * 13) % len(posts)]
        key = (u.id, p.id)
        i += 1
        if key in seen or p.owner_id == u.id:
            continue
        seen.add(key)
        row = PostConnection(
            id=deterministic_uuid("PostConnection", len(out)),
            user_id=u.id,
            post_id=p.id,
        )
        await session.merge(row)
        out.append(row)
    await session.commit()
    return out
