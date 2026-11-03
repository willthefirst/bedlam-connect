from uuid import UUID

from sqlalchemy import select

from src.domain.models import PostConnection
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class PostConnectionRepository(BaseRepository):
    async def get_by_pair(
        self, *, user_id: UUID, post_id: UUID
    ) -> PostConnection | None:
        stmt = select(PostConnection).filter(
            PostConnection.user_id == user_id,
            PostConnection.post_id == post_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def add_connection(self, *, user_id: UUID, post_id: UUID) -> PostConnection:
        return await self._persist_new(PostConnection(user_id=user_id, post_id=post_id))


get_post_connection_repository = register_repository(PostConnectionRepository)
