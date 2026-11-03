from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel


class PostConnection(BaseModel):
    """An edge from a user to a post they have reached out about. M:N: a
    user may connect to many posts and a post may be connected to by many
    users. The pair `(user_id, post_id)` is unique — the first message a
    user sends about a post creates the edge; later messages are no-ops
    at the DB level. `created_at` is the connection time. CASCADE on both
    FKs: deleting a user or post removes their edges.
    """

    __tablename__ = "post_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="uq_post_connections_user_post"),
        Index(
            "ix_post_connections_post_id_created_at",
            "post_id",
            "created_at",
        ),
    )

    user_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
    )

    user = relationship("User")
    post = relationship("Post")
