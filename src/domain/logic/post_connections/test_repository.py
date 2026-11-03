"""Tests for `PostConnectionRepository` — pair lookup and edge creation."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.post_connections.repository import PostConnectionRepository
from src.domain.models import Post
from tests.helpers import create_test_user, make_referral_detail

pytestmark = pytest.mark.asyncio


async def test_get_by_pair_returns_none_then_the_added_edge(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    author = create_test_user()
    post = Post(kind="referral", owner_id=author.id)
    post.referral_detail = make_referral_detail()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user, author, post])

    async with db_test_session_manager() as session:
        repo = PostConnectionRepository(session)
        assert await repo.get_by_pair(user_id=user.id, post_id=post.id) is None
        added = await repo.add_connection(user_id=user.id, post_id=post.id)
        await session.commit()

    async with db_test_session_manager() as session:
        repo = PostConnectionRepository(session)
        found = await repo.get_by_pair(user_id=user.id, post_id=post.id)
        assert found is not None
        assert found.id == added.id
        # The pair is directional: the author has no edge to their own post.
        assert await repo.get_by_pair(user_id=author.id, post_id=post.id) is None
