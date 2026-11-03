"""Audit-log helper for mutation handlers.

The audit row is written in the same transaction as the mutation itself
— the row is durable iff the mutation is (RESOURCE_GRAMMAR.md:135).
"""

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal
from uuid import UUID

from pydantic import BaseModel

from src.framework.access.actor.actor import Actor
from src.framework.audit.log import AuditLog
from src.framework.audit.repository import AuditRepository

logger = logging.getLogger(__name__)


def make_snapshotter(
    schema_cls: type[BaseModel],
) -> Callable[[Any], dict[str, Any]]:
    """Build a snapshotter that validates `obj` through `schema_cls` to a JSON-mode dict."""

    def _snapshot(obj: Any) -> dict[str, Any]:
        return schema_cls.model_validate(obj).model_dump(mode="json")

    return _snapshot


class AuditAction(str, Enum):
    """Closed vocabulary of mutation actions; `str` base lets values serialize
    transparently and compare equal to raw strings (persisted forever)."""

    CREATE_POST = "create_post"
    UPDATE_POST = "update_post"
    DELETE_POST = "delete_post"
    SET_USER_ACTIVATION = "set_user_activation"
    CREATE_USER = "create_user"
    UPDATE_USER = "update_user"
    DELETE_USER = "delete_user"
    REGISTER = "register"
    CREATE_ORGANIZATION = "create_organization"
    UPDATE_ORGANIZATION = "update_organization"
    DELETE_ORGANIZATION = "delete_organization"
    CREATE_CLINICIAN = "create_clinician"
    UPDATE_CLINICIAN = "update_clinician"
    DELETE_CLINICIAN = "delete_clinician"
    CREATE_PROGRAM = "create_program"
    UPDATE_PROGRAM = "update_program"
    DELETE_PROGRAM = "delete_program"
    CREATE_LICENSURE = "create_licensure"
    UPDATE_LICENSURE = "update_licensure"
    DELETE_LICENSURE = "delete_licensure"
    CREATE_EDUCATION = "create_education"
    UPDATE_EDUCATION = "update_education"
    DELETE_EDUCATION = "delete_education"
    CREATE_CERTIFICATION = "create_certification"
    UPDATE_CERTIFICATION = "update_certification"
    DELETE_CERTIFICATION = "delete_certification"
    CREATE_CLINICIAN_AFFILIATION = "create_clinician_affiliation"
    UPDATE_CLINICIAN_AFFILIATION = "update_clinician_affiliation"
    DELETE_CLINICIAN_AFFILIATION = "delete_clinician_affiliation"
    CREATE_SAVED_SEARCH = "create_saved_search"
    UPDATE_SAVED_SEARCH = "update_saved_search"
    DELETE_SAVED_SEARCH = "delete_saved_search"
    ADD_FAVORITE = "add_favorite"
    REMOVE_FAVORITE = "remove_favorite"
    JOB_RUN_STARTED = "job_run_started"
    # `PostConnection` (User↔Post edge) — created as a side effect of the
    # first `POST /posts/{id}/message` a user sends about a post. Create-
    # only (no disconnect), so there is no matching remove action. See
    # `_BESPOKE` in `test_audit_action_drift.py`.
    ADD_POST_CONNECTION = "add_post_connection"
    # `Verification` is append-only — only `CREATE_VERIFICATION` ever
    # fires. The triple is here (not just CREATE) because the
    # verification logic cluster declares a single `AuditedResource`
    # via `make_audited_resource(...)` (#528 / A4), and that helper
    # requires all three members. See `_BESPOKE` in
    # `test_audit_action_drift.py` for why these don't tie to an
    # EntitySpec.
    CREATE_VERIFICATION = "create_verification"
    UPDATE_VERIFICATION = "update_verification"
    DELETE_VERIFICATION = "delete_verification"
    # `OrgRepresentation` (User↔Org authority) — CRUD via the generic
    # `mount_entity` factories; `SET_ORG_REPRESENTATION_AUTHORITY` is the
    # state-axis action an admin invokes to flip `authority_status`
    # (pending → verified / rejected) without re-PUTing the whole row.
    CREATE_ORG_REPRESENTATION = "create_org_representation"
    UPDATE_ORG_REPRESENTATION = "update_org_representation"
    DELETE_ORG_REPRESENTATION = "delete_org_representation"
    SET_ORG_REPRESENTATION_AUTHORITY = "set_org_representation_authority"
    # State-axis action on `ClinicianLicensure` (owned subentity of
    # `Clinician`). The first consumer of `mount_state_axis` with
    # `spec.parent is not None` — re-attestation flips
    # `attested_active=True` + recomputes the license `status` and the
    # owning clinician's Claim-A cache.
    SET_LICENSE_ATTESTATION = "set_license_attestation"
    # Admin override of `Clinician.npi_match_status` /
    # `Organization.npi_match_status`. Used to close out a `mismatch`
    # the worker landed on (admin says "actually this person IS who
    # they claim — flip to matched") OR to re-queue (`pending`, worker
    # picks up again). Per-row state-axis surface so the audit trail
    # carries the override action distinctly from the worker's
    # `npi_resolved` events.
    SET_CLINICIAN_VERIFICATION_STATE = "set_clinician_verification_state"
    SET_ORG_VERIFICATION_STATE = "set_org_verification_state"


Verb = Literal["create", "update", "delete"]


@dataclass(frozen=True, slots=True)
class AuditedResource:
    """Declarative bundle for a CRUD-shaped audited resource."""

    type: str
    snapshot: Callable[[Any], dict[str, Any]]
    create: AuditAction
    update: AuditAction
    delete: AuditAction

    def action_for(self, verb: Verb) -> AuditAction:
        return getattr(self, verb)


def make_audited_resource(
    name: str,
    snapshot: Callable[[Any], dict[str, Any]] | type[BaseModel],
    *,
    action_stem: str | None = None,
) -> AuditedResource:
    """Build an `AuditedResource` from a name + snapshot."""
    stem = (action_stem or name).upper()
    if isinstance(snapshot, type) and issubclass(snapshot, BaseModel):
        snapshot_fn: Callable[[Any], dict[str, Any]] = make_snapshotter(snapshot)
    else:
        snapshot_fn = snapshot  # type: ignore[assignment]
    try:
        return AuditedResource(
            type=name,
            snapshot=snapshot_fn,
            create=AuditAction[f"CREATE_{stem}"],
            update=AuditAction[f"UPDATE_{stem}"],
            delete=AuditAction[f"DELETE_{stem}"],
        )
    except KeyError as exc:
        raise ValueError(
            f"make_audited_resource({name!r}): AuditAction has no member "
            f"matching CREATE_{stem}/UPDATE_{stem}/DELETE_{stem}. Add the "
            "members to AuditAction or pass action_stem= explicitly."
        ) from exc


async def record_audit(
    audit_repo: AuditRepository,
    *,
    actor_id: UUID | None,
    resource_type: str,
    resource_id: UUID,
    action: AuditAction,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """Record a single audit row. Returns the persisted row (flushed, not committed)."""
    row = await audit_repo.record(
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        before=before,
        after=after,
    )
    logger.info(f"Audit: actor={actor_id} {action.value} {resource_type}/{resource_id}")
    return row


async def record_audit_for(
    audit_repo: AuditRepository,
    *,
    resource: AuditedResource,
    verb: Verb,
    actor_id: UUID | None,
    target_id: UUID,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """Record an audit row for `resource` + `verb`."""
    return await record_audit(
        audit_repo,
        actor_id=actor_id,
        resource_type=resource.type,
        resource_id=target_id,
        action=resource.action_for(verb),
        before=before,
        after=after,
    )


@asynccontextmanager
async def mutate(
    repo: Any,
    audit_repo: AuditRepository,
    *,
    actor: Actor,
    target: Any,
    resource: AuditedResource,
    verb: Verb,
):
    """Snapshot-before / mutate / record_audit / commit ritual. Exceptions
    skip the audit row and commit so the transaction rolls back atomically —
    an audit row must never be durable without its matching mutation."""
    target_id: UUID = target.id
    before = None if verb == "create" else resource.snapshot(target)
    yield
    after = None if verb == "delete" else resource.snapshot(target)
    await record_audit_for(
        audit_repo,
        resource=resource,
        verb=verb,
        actor_id=actor.id,
        target_id=target_id,
        before=before,
        after=after,
    )
    await repo.session.commit()
    logger.info(
        f"Handler: actor={actor.id} {resource.action_for(verb).value} "
        f"{resource.type}/{target_id}"
    )
