"""Tests for `handle_send_post_message` — the message event that
creates a sender's `PostConnection` edge (#775).

Pins the load-bearing invariants:

- **First message creates the edge, once.** One `PostConnection` row and
  one `add_post_connection` audit row; later messages reuse the edge,
  write no audit row, and still send the email.
- **The body is never persisted.** Neither the edge nor its audit
  snapshot carries the message text.
- **No edge without a sent message.** The commit follows the email, so
  a failed send leaves nothing behind.
- **Authors can't message their own post** (403), even if a crafted
  request bypasses the hidden panel.

The `can_act_as_provider` gate itself is exercised end-to-end in
`src/domain/routes/test_posts.py`; here it's stubbed open.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.post_connections.repository import PostConnectionRepository
from src.domain.logic.posts.handlers import handle_send_post_message
from src.domain.logic.posts.repository import PostRepository
from src.domain.models import Post, PostConnection, User
from src.framework.audit.core import AuditAction
from src.framework.audit.log import AuditLog
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import ForbiddenError, NotFoundError
from tests.helpers import create_test_user, make_referral_detail

pytestmark = pytest.mark.asyncio

_BODY = "I have a client who would be a great fit"


@pytest.fixture
def send_mock(monkeypatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr("src.domain.logic.posts.handlers.send_post_message_email", mock)
    monkeypatch.setattr(
        "src.domain.logic.posts.handlers.capabilities.can_act_as_provider",
        lambda user: True,
    )
    return mock


async def _seed(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> tuple[User, User, Post]:
    sender = create_test_user(username=f"sender-{uuid.uuid4()}")
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = Post(kind="referral", owner_id=author.id)
    post.referral_detail = make_referral_detail()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([sender, author, post])
    return sender, author, post


async def _send(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    post_id,
    user: User,
):
    async with db_test_session_manager() as session:
        return await handle_send_post_message(
            post_id=post_id,
            body=_BODY,
            post_repo=PostRepository(session),
            connection_repo=PostConnectionRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=user,
        )


async def _connections(db_test_session_manager, user_id) -> list[PostConnection]:
    async with db_test_session_manager() as session:
        result = await session.execute(
            select(PostConnection).filter(PostConnection.user_id == user_id)
        )
        return list(result.scalars().all())


async def _connection_audits(db_test_session_manager) -> list[AuditLog]:
    async with db_test_session_manager() as session:
        result = await session.execute(
            select(AuditLog).filter(AuditLog.action == AuditAction.ADD_POST_CONNECTION)
        )
        return list(result.scalars().all())


async def test_first_message_creates_edge_and_audits(
    db_test_session_manager, send_mock
):
    sender, _, post = await _seed(db_test_session_manager)

    sent = await _send(db_test_session_manager, post_id=post.id, user=sender)

    assert sent.newly_connected is True
    edges = await _connections(db_test_session_manager, sender.id)
    assert [e.post_id for e in edges] == [post.id]
    audits = await _connection_audits(db_test_session_manager)
    assert len(audits) == 1
    assert audits[0].resource_type == "post_connection"
    assert audits[0].resource_id == edges[0].id
    assert audits[0].actor_id == sender.id
    assert audits[0].before is None
    assert set(audits[0].after) == {"id", "user_id", "post_id", "created_at"}
    assert send_mock.call_count == 1
    assert send_mock.call_args.kwargs["body"] == _BODY


async def test_repeat_message_reuses_edge_without_audit(
    db_test_session_manager, send_mock
):
    sender, _, post = await _seed(db_test_session_manager)

    first = await _send(db_test_session_manager, post_id=post.id, user=sender)
    second = await _send(db_test_session_manager, post_id=post.id, user=sender)

    assert second.newly_connected is False
    assert second.connection.id == first.connection.id
    assert len(await _connections(db_test_session_manager, sender.id)) == 1
    assert len(await _connection_audits(db_test_session_manager)) == 1
    assert send_mock.call_count == 2


async def test_body_is_not_persisted(db_test_session_manager, send_mock):
    sender, _, post = await _seed(db_test_session_manager)

    await _send(db_test_session_manager, post_id=post.id, user=sender)

    audits = await _connection_audits(db_test_session_manager)
    assert _BODY not in str(audits[0].after)
    assert "body" not in PostConnection.__table__.columns


async def test_failed_send_records_no_edge(db_test_session_manager, send_mock):
    sender, _, post = await _seed(db_test_session_manager)
    send_mock.side_effect = RuntimeError("mail provider down")

    with pytest.raises(RuntimeError):
        await _send(db_test_session_manager, post_id=post.id, user=sender)

    assert await _connections(db_test_session_manager, sender.id) == []
    assert await _connection_audits(db_test_session_manager) == []


async def test_author_cannot_message_own_post(db_test_session_manager, send_mock):
    _, author, post = await _seed(db_test_session_manager)

    with pytest.raises(ForbiddenError):
        await _send(db_test_session_manager, post_id=post.id, user=author)

    assert send_mock.call_count == 0
    assert await _connections(db_test_session_manager, author.id) == []


async def test_missing_post_is_404(db_test_session_manager, send_mock):
    sender, _, _ = await _seed(db_test_session_manager)

    with pytest.raises(NotFoundError):
        await _send(db_test_session_manager, post_id=uuid.uuid4(), user=sender)

    assert send_mock.call_count == 0
