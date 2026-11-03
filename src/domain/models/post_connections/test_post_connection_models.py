"""DB-layer tests for `PostConnection`.

Pins what the table owns: the `(user_id, post_id)` uniqueness pin
(a second edge for the same pair raises `IntegrityError`), and the
CASCADE behavior on both FKs — deleting either the user or the post
purges the edge.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Post, PostConnection, User
from tests.helpers import create_test_user, make_referral_detail

pytestmark = pytest.mark.asyncio


async def _seed_user_and_post(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> tuple[User, Post]:
    user = create_test_user()
    author = create_test_user()
    post = Post(kind="referral", owner_id=author.id)
    post.referral_detail = make_referral_detail()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(author)
            session.add(post)
    return user, post


async def _edges_for(
    db_test_session_manager: async_sessionmaker[AsyncSession], *filters
) -> list[PostConnection]:
    async with db_test_session_manager() as session:
        result = await session.execute(select(PostConnection).filter(*filters))
        return list(result.scalars().all())


async def test_create_post_connection_persists(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, post = await _seed_user_and_post(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(PostConnection(user_id=user.id, post_id=post.id))

    rows = await _edges_for(db_test_session_manager, PostConnection.user_id == user.id)
    assert len(rows) == 1
    assert rows[0].post_id == post.id
    assert rows[0].created_at is not None


async def test_duplicate_pair_violates_unique_constraint(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, post = await _seed_user_and_post(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(PostConnection(user_id=user.id, post_id=post.id))

    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(PostConnection(user_id=user.id, post_id=post.id))


async def test_delete_user_cascades_connections(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, post = await _seed_user_and_post(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(PostConnection(user_id=user.id, post_id=post.id))

    async with db_test_session_manager() as session:
        async with session.begin():
            await session.delete(await session.get(User, user.id))

    assert (
        await _edges_for(db_test_session_manager, PostConnection.user_id == user.id)
        == []
    )


async def test_delete_post_cascades_connections(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, post = await _seed_user_and_post(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(PostConnection(user_id=user.id, post_id=post.id))

    async with db_test_session_manager() as session:
        async with session.begin():
            await session.delete(await session.get(Post, post.id))

    assert (
        await _edges_for(db_test_session_manager, PostConnection.post_id == post.id)
        == []
    )
