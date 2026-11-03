from functools import partial

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import (
    ADMIN_NOTE_ACTIONS,
    ADMIN_NOTE_SUBJECTS,
    CHECK_IN_REPLIES,
    CONNECTION_VERDICTS,
    check_in_tuple_sql,
    named_check_in,
)

_TABLE = "admin_notes"
_ck = partial(named_check_in, _TABLE)


class AdminNote(BaseModel):
    """Something the admin did or learned about a connection, post, or
    member — the observability log behind the Datasette daily queries
    (`src/domain/logic/admin_data/`).

    Written **only** by Datasette's "Add a note" canned query, never by
    the app, so the CHECKs here are the only validation a row gets:
    `value` must match `action` (a check-in reply is yes / not yet / no;
    a verdict is good / not good; other actions carry no value).

    `subject_id` is a bare UUID with no FK: it points at a
    `post_connections`, `posts`, or `users` row depending on
    `subject_type`, and a note should outlive a deleted subject.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("subject_type", ADMIN_NOTE_SUBJECTS),
        _ck("action", ADMIN_NOTE_ACTIONS),
        CheckConstraint(
            "value IS NULL"
            f" OR (action = 'check_in_reply' AND {check_in_tuple_sql('value', CHECK_IN_REPLIES)})"
            f" OR (action = 'verdict' AND {check_in_tuple_sql('value', CONNECTION_VERDICTS)})",
            name=f"ck_{_TABLE}_value",
        ),
        Index("ix_admin_notes_subject", "subject_type", "subject_id"),
    )

    subject_type = Column(Text, nullable=False)
    subject_id = Column(Uuid(as_uuid=True), nullable=False)
    action = Column(Text, nullable=False)
    value = Column(Text, nullable=True)
    note = Column(Text, nullable=True)
    author_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    author = relationship("User")
