from uuid import UUID

from fastapi import Depends, Request
from pydantic import BaseModel, Field, field_validator

from src.auth_config import current_active_user
from src.domain.logic.post_connections.repository import (
    PostConnectionRepository,
    get_post_connection_repository,
)
from src.domain.logic.posts.handlers import handle_send_post_message
from src.domain.logic.posts.repository import PostRepository, get_post_repository
from src.domain.models import User
from src.domain.specs import POST_ENTITY
from src.framework import register_entity
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.resource_routes import mount_entity
from src.framework.http.responses import APIResponse
from src.framework.persistence.dependencies import get_audit_repository

router = register_entity(POST_ENTITY)


# Whole-supertype face of the polymorphic post entity — one URL family
# (`/posts`) lists every kind. `?kind=<value>` selects the create-form
# template at `GET /posts/form`; the discriminated-union body adapter
# dispatches POST/PATCH bodies by their declared `kind`.
mount_entity(router, POST_ENTITY)


# Maximum body length — chosen to comfortably fit "I have a referral
# that matches; here's a few sentences about availability" without
# becoming an entire email's worth of free text. The cap exists to
# bound the outbound transactional-email size, not to be a UX limit
# the user is meant to feel; bumping it later is cheap.
_MESSAGE_BODY_MAX_LEN = 2000


class _PostMessageBody(BaseModel):
    """Wire shape for `POST /posts/{post_id}/message` — a sender's
    free-text body. The body is rendered as plain text (escaped in
    the HTML part) into the outbound email; there is no DB row.

    Field validators strip surrounding whitespace and reject
    empty-after-strip submissions, matching the implicit contract a
    `<textarea required>` carries on the client side."""

    body: str = Field(..., max_length=_MESSAGE_BODY_MAX_LEN)

    @field_validator("body")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("body must not be empty")
        return stripped


@router.post("/{post_id}/message", name="post:message_send")
async def send_post_message(
    post_id: UUID,
    body_in: _PostMessageBody,
    request: Request,
    post_repo: PostRepository = Depends(get_post_repository),
    connection_repo: PostConnectionRepository = Depends(get_post_connection_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    requesting_user: User = Depends(current_active_user),
):
    """In-app "message the poster" event endpoint.

    Event-shaped (RESOURCE_GRAMMAR § "POST /<r>/{id}/<event>") — fires
    an outbound transactional email to the post owner with the
    sender's email on `Reply-To`, and records the sender's
    `PostConnection` edge on their first message about the post (#775)
    plus a `send_post_message` audit event on every send.
    The message body itself is never persisted: the conversation
    continues off-platform in the poster's own mail client, so any body
    history we'd store would only diverge from what actually happened.
    The edge records only *that* the sender reached out.

    Authz: the sender must clear `can_act_as_provider` and must not own
    the post. Orchestration lives in `handle_send_post_message`.

    Returns an HTML fragment HTMX swaps over the form in place.
    """
    sent = await handle_send_post_message(
        post_id=post_id,
        body=body_in.body,
        post_repo=post_repo,
        connection_repo=connection_repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
    )
    return APIResponse.html_response(
        template_name="posts/_message_sent.html",
        context={
            "post": sent.post,
            "connection": sent.connection,
            "newly_connected": sent.newly_connected,
        },
        request=request,
        current_user=requesting_user,
    )
