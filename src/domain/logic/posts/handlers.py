"""Per-spec hook callables for the `Post` entity.

`_assert_post_payload_authz` is the entry point driven by
``POST_ENTITY.payload_authz_path``: it layers FK-ownership (the
submitter must own the cross-entity row the post references) AND the
capability gate from the two-claim verification model (a referral / a
clinician-opening requires Claim A; a program-intake requires Claim B
for the org behind the referenced Program).

Why it dispatches on ``payload.kind``: all three kinds reference a
cross-entity FK the submitting user must own.
``clinician_opening.clinician_id`` and ``program_intake.program_id``
point at rows the user created; ``referral.referring_clinician_id``
points at a Clinician the user owns. The cleaner long-term shape is
per-kind authz on :class:`PostKindSpec`; a type-switching dispatcher is
acceptable while the kind set is small.
"""

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

from src.domain.logic import capabilities
from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.post_connections.repository import PostConnectionRepository
from src.domain.logic.post_connections.schema import PostConnectionAuditSnapshot
from src.domain.logic.posts.emails import send_post_message_email
from src.domain.logic.posts.repository import PostRepository
from src.domain.logic.programs.repository import ProgramRepository
from src.domain.models import (
    Clinician,
    ClinicianAffiliation,
    Organization,
    Post,
    PostConnection,
    Program,
    User,
)
from src.framework.access.authz.authz import assert_fk_ownership
from src.framework.audit.core import AuditAction, make_snapshotter, record_audit
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.pagination import (
    DEFAULT_PAGE_SIZE,
    Pager,
    base_query,
    offset_for,
    paginate,
    parse_page,
)
from src.framework.http.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)

# Per-kind mapping for the FK-ownership check. Each entry says: when the
# payload's `kind` matches, validate that the named attribute points at a
# row of `model` (loaded via `repo`) that the requesting user owns.
_KIND_FK_TARGETS: tuple[tuple[str, str, str, type], ...] = (
    # (kind, attr, parent_noun, parent_model)
    ("clinician_opening", "clinician_id", "Clinician", Clinician),
    ("program_intake", "program_id", "Program", Program),
    ("referral", "referring_clinician_id", "Clinician", Clinician),
)


async def _assert_post_payload_authz(
    *,
    payload: BaseModel,
    requesting_user: User,
    clinician_repo: ClinicianRepository,
    program_repo: ProgramRepository,
    organization_repo: OrganizationRepository,
) -> None:
    """`POST_ENTITY.payload_authz_path` target — authorizes a post
    create payload via one of two authority paths.

    First ``_resolve_affiliation_context`` derives the listing's
    clinician FK from the picker-submitted ``clinician_affiliation_id``
    (clinician-authored kinds only) and returns the resolved
    affiliation. Authority then resolves as:

    1. **Org-rep (Claim B) path** — if the payload carries an
       affiliation and the requesting user is a *verified org rep*
       (`capabilities.org_rep_verified`) for that affiliation's org,
       the write is authorized. This lets a group-practice coordinator
       post a referral/opening under an affiliated clinician they don't
       *own*, without holding Claim A themselves — the org-rep authority
       chain (`OrgRepresentation` → org → affiliation → clinician).

    2. **Self (owner + Claim A) path** — otherwise the per-kind FK on
       the payload must point at a row the requesting user owns
       (:func:`_assert_post_payload_target_ownership`) AND the user must
       hold the claim that gates this post-kind
       (:func:`_assert_post_payload_capability`):

       - ``referral`` / ``clinician_opening`` → Claim A
         (`capabilities.clinician_verified(user)`), via the sync
         :func:`_assert_post_payload_capability`.
       - ``program_intake`` → Claim B for the referenced Program's org
         (`capabilities.can_post_program_intake(user, org)`), via the
         async :func:`_assert_program_intake_org_rep` — split out because
         the check needs the program's org id, which requires a DB read.

    Superusers fall through to the self path, where both the ownership
    and capability checks bypass for admins — so an admin still writes
    any row. ``program_intake`` carries no affiliation, so it always
    takes the self path (its org authority is the Program's owning org,
    handled there).

    **Create-only.** The org-rep path is wired on create
    (`mount_create` runs only ``payload_authz`` on the not-yet-existing
    post). Editing a post one doesn't own is still gated by the
    object-level ``write_authz`` (owner-or-admin) that runs before this
    hook on PATCH — expanding *that* to the org-rep chain needs an async
    object-level policy and is a separate change.
    """
    affiliation = await _resolve_affiliation_context(
        payload=payload, clinician_repo=clinician_repo
    )
    if affiliation is not None and await _is_verified_org_rep_for_affiliation(
        affiliation=affiliation,
        requesting_user=requesting_user,
        organization_repo=organization_repo,
    ):
        return
    await _assert_post_payload_target_ownership(
        payload=payload,
        requesting_user=requesting_user,
        clinician_repo=clinician_repo,
        program_repo=program_repo,
    )
    _assert_post_payload_capability(payload, requesting_user)
    await _assert_program_intake_org_rep(
        payload=payload,
        requesting_user=requesting_user,
        program_repo=program_repo,
        organization_repo=organization_repo,
    )


async def _is_verified_org_rep_for_affiliation(
    *,
    affiliation: ClinicianAffiliation,
    requesting_user: User,
    organization_repo: OrganizationRepository,
) -> bool:
    """True iff ``requesting_user`` holds verified Claim B for the org
    the affiliation points at.

    The affiliation *is* the clinician↔org link, so resolving its
    ``org_id`` and checking `capabilities.org_rep_verified(user, org)`
    fully captures the org-rep authority chain — the
    "clinician affiliated to org" leg of `can_post_org_referral` is
    tautological when the affiliation is the source of truth. Returns
    False (rather than raising) on any miss so the caller falls through
    to the self/owner authority path."""
    org = await organization_repo.get_by_model_id(Organization, affiliation.org_id)
    if org is None:
        return False
    return capabilities.org_rep_verified(requesting_user, org)


async def _resolve_affiliation_context(
    *, payload: BaseModel, clinician_repo: ClinicianRepository
) -> ClinicianAffiliation | None:
    """Derive the listing's clinician FK from the picker's affiliation.

    The opening / referral create+edit forms expose a single practice
    picker whose options are the acting user's ``ClinicianAffiliation``
    rows (one per clinician×org). The picker submits
    ``clinician_affiliation_id``; the listing's persisted clinician FK
    (``clinician_id`` for openings, ``referring_clinician_id`` for
    referrals) is *derived* from that affiliation's ``clinician_id`` so
    the two can never disagree — and so a clinician affiliated with two
    orgs no longer collapses both options onto the same value.

    Sets the derived FK on ``payload`` in place (Pydantic v2 marks it in
    ``model_fields_set``, so ``model_dump(exclude_unset=True)`` carries
    it into the update path too). Runs before the ownership check, which
    then validates the resolved clinician.

    Returns the loaded ``ClinicianAffiliation`` (so the caller can reach
    its ``org_id`` for the org-rep authority path), or ``None`` when the
    payload carries no ``clinician_affiliation_id`` — a ``program_intake``
    payload (no such field) or a referral/opening PATCH that leaves
    context unchanged. 404 when the id doesn't resolve.
    """
    aff_id = getattr(payload, "clinician_affiliation_id", None)
    if aff_id is None:
        return None
    affiliation = await clinician_repo.get_by_model_id(ClinicianAffiliation, aff_id)
    if affiliation is None:
        raise NotFoundError(detail=f"Clinician affiliation {aff_id} not found")
    derived_attr = (
        "referring_clinician_id"
        if getattr(payload, "kind", None) == "referral"
        else "clinician_id"
    )
    setattr(payload, derived_attr, affiliation.clinician_id)
    return affiliation


def _assert_post_payload_capability(payload: BaseModel, requesting_user: User) -> None:
    """Per-kind Claim-A capability gate. Stays sync because the
    underlying predicates (`can_post_referral`, `can_post_opening`)
    only read off the user object and don't touch the database.
    Superusers bypass — admin writes override the claim-based gate.

    `program_intake`'s Claim-B gate lives in the async
    :func:`_assert_program_intake_org_rep` helper, called from the
    orchestrator immediately after this one. Split because the
    Claim-B check needs the target program's org id — a DB read."""
    if getattr(requesting_user, "is_superuser", False):
        return
    kind = getattr(payload, "kind", None)
    if kind == "referral" and not capabilities.can_post_referral(requesting_user):
        raise ForbiddenError(
            detail=(
                "Posting a referral requires a verified clinician profile "
                "(Claim A). Visit /users/me to complete verification."
            ),
        )
    if kind == "clinician_opening" and not capabilities.can_post_opening(
        requesting_user
    ):
        raise ForbiddenError(
            detail=(
                "Posting a clinician opening requires a verified clinician "
                "profile (Claim A). Visit /users/me to complete verification."
            ),
        )


async def _assert_program_intake_org_rep(
    *,
    payload: BaseModel,
    requesting_user: User,
    program_repo: ProgramRepository,
    organization_repo: OrganizationRepository,
) -> None:
    """Per-row Claim-B check for `program_intake` payloads.

    Loads the referenced `Program`, walks to its `Organization`, and
    asserts `capabilities.can_post_program_intake(user, org)`. This
    closes the gap the picker-side `check_program_intake` already
    expresses on `/posts/form`: without it, a user who owns a Program
    under an unverified org could direct-POST `kind=program_intake`
    and bypass the locked tile.

    No-op when:
    - kind is not `program_intake` (referral/opening go through the
      sync Claim-A helper above);
    - the user is a superuser (admin writes bypass);
    - the payload omits `program_id` (a PATCH that doesn't touch the
      FK — though create requires it); or
    - the program/org row isn't loadable (already 404'd by
      :func:`_assert_post_payload_target_ownership` upstream — re-
      checking here would only mask the upstream error).

    403s with the `program-intake` capability detail URL so the user
    lands on the same explainer the picker popover points at."""
    if getattr(requesting_user, "is_superuser", False):
        return
    if getattr(payload, "kind", None) != "program_intake":
        return
    program_id = getattr(payload, "program_id", None)
    if program_id is None:
        return
    program = await program_repo.get_by_model_id(Program, program_id)
    if program is None:
        return
    org = await organization_repo.get_by_model_id(Organization, program.org_id)
    if org is None or not capabilities.can_post_program_intake(requesting_user, org):
        raise ForbiddenError(
            detail=(
                "Posting a program intake requires a verified organization "
                "claim (Claim B) for the program's owning organization. "
                "Visit /users/me/access/capabilities/program-intake."
            ),
        )


async def _assert_post_payload_target_ownership(
    *,
    payload: BaseModel,
    requesting_user: User,
    clinician_repo: ClinicianRepository,
    program_repo: ProgramRepository,
) -> None:
    """Reject a Post create/update whose per-kind FK points at a row
    the requesting user doesn't own (superusers bypass).

    Dispatches on ``payload.kind`` via :data:`_KIND_FK_TARGETS`:

    * ``clinician_opening`` — checks ``payload.clinician_id`` against
      ``Clinician.owner_id``.
    * ``program_intake`` — checks ``payload.program_id`` against
      ``Program.owner_id``.
    * ``referral`` — checks ``payload.referring_clinician_id`` against
      ``Clinician.owner_id``.

    404 when the target row doesn't exist (no info leak about other
    users' ids); 403 when it exists but belongs to someone else. PATCH
    payloads where the FK field is None (the PATCH doesn't touch the
    FK) are a no-op — only flow through the ownership check when the
    payload is actually trying to set a new target. Both branches share
    the generic :func:`~src.framework.access.authz.authz.assert_fk_ownership` helper.

    See module docstring for why the dispatcher lives here rather than
    on :class:`PostKindSpec` per-kind."""
    kind = getattr(payload, "kind", None)
    repos = {
        "clinician_id": clinician_repo,
        "program_id": program_repo,
        "referring_clinician_id": clinician_repo,
    }
    for target_kind, attr, parent_noun, parent_model in _KIND_FK_TARGETS:
        if kind != target_kind:
            continue
        await assert_fk_ownership(
            payload=payload,
            attr=attr,
            requesting_user=requesting_user,
            parent_repo=repos[attr],
            parent_model=parent_model,
            parent_noun=parent_noun,
            child_noun="post",
        )
        return


# ── Owner-scoped read projections (RESOURCE_GRAMMAR pattern #5) ──────────
#
# `/clinicians/{id}/openings`, `/clinicians/{id}/referrals`, and
# `/organizations/{id}/intakes` are filtered views over the same `/posts`
# supertype — no new ownership, no schema change. Each handler is the
# target of a `RelatedListSubresource.handler_path` on the parent entity
# spec; the mount injects `repo` (the *post* repo, since the rows are
# posts), the parent id under the parent's `id_param`, `requesting_user`,
# and any extra typed repo the handler declares.


async def handle_list_clinician_openings(
    request: Request,
    clinician_id: UUID,
    repo: PostRepository,
    clinician_repo: ClinicianRepository,
    requesting_user: User,
) -> dict[str, Any]:
    clinician = await clinician_repo.get_by_model_id(Clinician, clinician_id)
    if clinician is None:
        raise NotFoundError(detail=f"Clinician {clinician_id} not found")
    return await _post_owner_list_context(
        request=request,
        owner=clinician,
        owner_key="clinician",
        rows_coro=repo.list_clinician_openings,
        owner_id=clinician_id,
        requesting_user=requesting_user,
    )


async def handle_list_clinician_referrals(
    request: Request,
    clinician_id: UUID,
    repo: PostRepository,
    clinician_repo: ClinicianRepository,
    requesting_user: User,
) -> dict[str, Any]:
    clinician = await clinician_repo.get_by_model_id(Clinician, clinician_id)
    if clinician is None:
        raise NotFoundError(detail=f"Clinician {clinician_id} not found")
    return await _post_owner_list_context(
        request=request,
        owner=clinician,
        owner_key="clinician",
        rows_coro=repo.list_clinician_referrals,
        owner_id=clinician_id,
        requesting_user=requesting_user,
    )


async def handle_list_org_intakes(
    request: Request,
    organization_id: UUID,
    repo: PostRepository,
    organization_repo: OrganizationRepository,
    requesting_user: User,
) -> dict[str, Any]:
    org = await organization_repo.get_by_model_id(Organization, organization_id)
    if org is None:
        raise NotFoundError(detail=f"Organization {organization_id} not found")
    return await _post_owner_list_context(
        request=request,
        owner=org,
        owner_key="organization",
        rows_coro=repo.list_org_intakes,
        owner_id=organization_id,
        requesting_user=requesting_user,
    )


async def _post_owner_list_context(
    *,
    request: Request,
    owner: Any,
    owner_key: str,
    rows_coro,
    owner_id: UUID,
    requesting_user: User,
) -> dict[str, Any]:
    """Shared paginate-and-project body for the three owner-scoped post
    lists. `owner_key` names the owner in the template context
    ("clinician" / "organization"); `rows_coro` is the bound repo method
    that returns the owner's posts."""
    page_number = parse_page(request)
    per_page = DEFAULT_PAGE_SIZE
    rows_plus_one = await rows_coro(
        owner_id,
        offset=offset_for(page_number, per_page),
        limit=per_page + 1,
    )
    posts, page = paginate(rows_plus_one, page=page_number, per_page=per_page)
    return {
        "request": request,
        owner_key: owner,
        "posts": posts,
        "is_self": getattr(owner, "owner_id", None) == requesting_user.id,
        "can_act_as_provider": capabilities.can_act_as_provider(requesting_user),
        "current_user": requesting_user,
        "pager": Pager(page=page, base_query=base_query(request)),
    }


_CONNECTION_SNAPSHOT = make_snapshotter(PostConnectionAuditSnapshot)


@dataclass(frozen=True, slots=True)
class SentPostMessage:
    """Result of `handle_send_post_message`. `newly_connected` is True
    only when this message created the edge — the success fragment uses
    it to announce the connection once, without duplicating the
    "Connected" line the panel already shows for an existing edge."""

    post: Post
    connection: PostConnection
    newly_connected: bool


async def handle_send_post_message(
    *,
    post_id: UUID,
    body: str,
    post_repo: PostRepository,
    connection_repo: PostConnectionRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> SentPostMessage:
    """Email `body` to the post's owner and record the sender's connection.

    The first message a user sends about a post creates their
    `PostConnection` edge (audited as `add_post_connection`); later messages
    reuse the existing edge. Every send — first or repeat — also writes a
    `send_post_message` event row against the connection, so the audit
    log is the per-message history (who, which post, when). The body is
    never persisted — it lives only in the outbound email.

    The commit runs after the email sends, so a failed send leaves no
    edge and no event row behind: each row means a message actually
    went out.

    403 if the sender doesn't clear `can_act_as_provider` or owns the
    post; 404 if the post does not exist.
    """
    if not capabilities.can_act_as_provider(requesting_user):
        raise ForbiddenError(detail="Provider network access required.")
    post = await post_repo.get_by_model_id(Post, post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")
    if post.owner_id == requesting_user.id:
        raise ForbiddenError(detail="You can't message your own post.")

    connection = await connection_repo.get_by_pair(
        user_id=requesting_user.id, post_id=post_id
    )
    newly_connected = connection is None
    if connection is None:
        connection = await connection_repo.add_connection(
            user_id=requesting_user.id, post_id=post_id
        )
        await record_audit(
            audit_repo,
            actor_id=requesting_user.id,
            resource_type="post_connection",
            resource_id=connection.id,
            action=AuditAction.ADD_POST_CONNECTION,
            before=None,
            after=_CONNECTION_SNAPSHOT(connection),
        )

    await send_post_message_email(post=post, sender=requesting_user, body=body)
    # Event row: nothing is mutated, so no before/after snapshot — the
    # actor + connection id + timestamp are the whole record.
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="post_connection",
        resource_id=connection.id,
        action=AuditAction.SEND_POST_MESSAGE,
    )
    await connection_repo.session.commit()
    logger.info(f"Handler: user {requesting_user.id} messaged post {post_id}")
    return SentPostMessage(
        post=post, connection=connection, newly_connected=newly_connected
    )


async def post_detail_extras(
    *,
    target: Post,
    requesting_user: User | None,
    post_connection_repo: PostConnectionRepository,
    **_: Any,
) -> dict[str, Any]:
    """Per-viewer detail context: the viewer's connection to this post,
    if any. The connect panel shows "Connected · {date}" when present."""
    if requesting_user is None:
        return {"connection": None}
    return {
        "connection": await post_connection_repo.get_by_pair(
            user_id=requesting_user.id, post_id=target.id
        ),
    }
