"""Wire schemas for `PostConnection` — the user→post M:N edge.

The edge has no wire surface of its own: it is created as a side effect
of `POST /posts/{post_id}/message` and never updated or removed. The
only schema needed is `PostConnectionAuditSnapshot`, the `after`
capture on the `add_post_connection` audit row. It carries ids and the
timestamp only — never the message body.
"""

import uuid
from datetime import datetime

from src.framework.schema_validators import ReadProjection


class PostConnectionAuditSnapshot(ReadProjection):
    id: uuid.UUID
    user_id: uuid.UUID
    post_id: uuid.UUID
    created_at: datetime
