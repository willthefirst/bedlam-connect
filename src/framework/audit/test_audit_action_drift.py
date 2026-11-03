"""Drift guard: every `AuditAction` member is justified by a spec and
follows the naming grammar in `README.md` § "`AuditAction` naming".

The CRUD / edge / state-axis partition is derived by iterating
:data:`src.domain.specs.ALL_ENTITY_SPECS` — no hand-listed tuple per
audit shape. Adding a new entity means adding it to that re-export
tuple and the matching ``CREATE_<STEM>`` / ``UPDATE_<STEM>`` /
``DELETE_<STEM>`` members to :class:`AuditAction`; this drift guard
flags any missing piece.
"""

import re

import pytest

from src.domain.specs import ALL_ENTITY_SPECS
from src.framework.audit.core import AuditAction

# Verb prefixes allowed for resource-mutating actions, per audit shape.
# See README.md § "`AuditAction` naming" for the table this mirrors.
_CRUD_VERBS = ("CREATE", "UPDATE", "DELETE")
_EDGE_VERBS = {"add": "ADD", "remove": "REMOVE"}
_STATE_AXIS_VERB = "SET"
_MUTATION_NAME = re.compile(
    rf"^({'|'.join((*_CRUD_VERBS, *_EDGE_VERBS.values(), _STATE_AXIS_VERB))})_[A-Z][A-Z0-9_]*$"
)

# Event actions: nothing is mutated, so there is no `<VERB>_<RESOURCE>`
# shape to follow. Keep tight — an action that creates or changes a row
# belongs in one of the verb families above, not here.
_EVENT_ACTIONS: frozenset[str] = frozenset(
    {"REGISTER", "JOB_RUN_STARTED", "SEND_POST_MESSAGE"}
)

# Bespoke members not modeled by any spec.
#
# - `REGISTER` is fired by the fastapi-users self-signup flow in
#   `src/logic/auth/auth_processing.py` — there is no `RegistrationEntity`
#   spec, the verb just sits on top of `User`.
# - `JOB_RUN_STARTED` is fired by APScheduler-driven background jobs in
#   `src/jobs/` (system actor; `resource_type="job"`; per-run `resource_id`).
#   There is no spec home: a "job ran" event has no `AuditedResource` shape.
# - `CREATE_VERIFICATION` / `UPDATE_VERIFICATION` / `DELETE_VERIFICATION`
#   back the `AuditedResource` declared in
#   `src/domain/logic/verifications/handlers.py` (#528 / A4). Verification
#   has no public CRUD surface — the orchestrator writes append-only rows
#   from a bespoke trigger endpoint — so there is no EntitySpec for the
#   drift checker to derive these from. `make_audited_resource("verification", ...)`
#   still requires the full CREATE/UPDATE/DELETE triple as a precondition,
#   which is why UPDATE and DELETE are listed even though only CREATE is
#   wired to a callsite today.
# - `ADD_POST_CONNECTION` is fired by `handle_send_post_message` in
#   `src/domain/logic/posts/handlers.py` when a user's first message about
#   a post creates their `PostConnection` edge. The edge has no routes of
#   its own (it rides the `/posts/{id}/message` event) and no remove verb,
#   so there is no EntitySpec / `EdgeAudit` to derive it from.
# - `SEND_POST_MESSAGE` is the per-send event row the same handler writes
#   on every message (first or repeat), against the sender's
#   `PostConnection`. An event, not a mutation — nothing changes — so it
#   sits in `_EVENT_ACTIONS` too.
#
# Keep tight: add an entry only when adding a corresponding
# `record_audit(action=...)` callsite or `AuditedResource` declaration.
_BESPOKE: frozenset[str] = frozenset(
    {
        "REGISTER",
        "JOB_RUN_STARTED",
        "CREATE_VERIFICATION",
        "UPDATE_VERIFICATION",
        "DELETE_VERIFICATION",
        "ADD_POST_CONNECTION",
        "SEND_POST_MESSAGE",
    }
)


def _expected_members() -> set[str]:
    expected: set[str] = set(_BESPOKE)
    for spec in ALL_ENTITY_SPECS:
        if spec.audit is not None:
            # The stem for the *enum member name* comes off the
            # AuditedResource's own create/update/delete action names,
            # not from `spec.name` directly — kind-locked faces of a
            # polymorphic supertype (`discriminator_value` set) share
            # one AuditedResource whose stem is the supertype name
            # ("post"), not the face name ("referral" etc.). Reading
            # through `spec.audit` keeps the test correct for both
            # shapes without a special case.
            expected.add(spec.audit.create.name)
            expected.add(spec.audit.update.name)
            expected.add(spec.audit.delete.name)
        if spec.edge_audit is not None:
            for action in spec.edge_audit.actions.values():
                expected.add(action.name)
        for axis in spec.state_axes:
            expected.add(axis.action.name)
    return expected


def test_audit_action_members_match_specs():
    """Every `AuditAction` member must be justified by a spec (CRUD
    triple, edge action, state-axis action) or the bespoke allow-list.

    Adding a spec → import-time `make_audited_resource` will require
    the matching members. Removing a spec → this test fails until the
    orphaned members are removed from the enum. Values are persisted
    forever, so dropping an enum value is a deliberate migration step.
    """
    declared = {member.name for member in AuditAction}
    expected = _expected_members()

    missing = expected - declared
    extra = declared - expected

    assert not missing, (
        f"AuditAction is missing members referenced by specs: "
        f"{sorted(missing)}. Add them to AuditAction or fix the spec."
    )
    assert not extra, (
        f"AuditAction has orphaned members with no spec home: "
        f"{sorted(extra)}. Either add a spec that uses them, list "
        f"them in _BESPOKE, or remove them from the enum (after "
        f"confirming no persisted audit rows still reference the value)."
    )


@pytest.mark.parametrize("member", list(AuditAction), ids=lambda m: m.name)
def test_audit_action_name_follows_grammar(member: AuditAction):
    """Every member is `<VERB>_<RESOURCE>` with a verb from one of the
    audit-shape families, or a listed event. Values are persisted
    forever, so a misnamed member can't be fixed after it ships."""
    assert member.name in _EVENT_ACTIONS or _MUTATION_NAME.match(member.name), (
        f"AuditAction.{member.name} doesn't follow the naming grammar. Use "
        f"CREATE_/UPDATE_/DELETE_ (CRUD), ADD_/REMOVE_ (edge) or SET_ "
        f"(state axis) + the resource name, or list a true no-mutation "
        f"event in _EVENT_ACTIONS. See src/framework/audit/README.md."
    )


@pytest.mark.parametrize("member", list(AuditAction), ids=lambda m: m.name)
def test_audit_action_value_is_lowercased_name(member: AuditAction):
    assert member.value == member.name.lower()


def test_spec_declared_actions_use_their_shape_verb():
    """The verb must match the shape that declares it: a CRUD triple is
    CREATE/UPDATE/DELETE, an edge's `add`/`remove` are ADD_/REMOVE_, a
    state axis is SET_. Catches e.g. an edge spec mapping `add` to a
    `CREATE_*` member."""
    wrong: list[str] = []
    for spec in ALL_ENTITY_SPECS:
        if spec.audit is not None:
            for verb, action in zip(
                _CRUD_VERBS,
                (spec.audit.create, spec.audit.update, spec.audit.delete),
                strict=True,
            ):
                if not action.name.startswith(f"{verb}_"):
                    wrong.append(f"{spec.name}.audit {verb}: {action.name}")
        if spec.edge_audit is not None:
            for verb, action in spec.edge_audit.actions.items():
                prefix = _EDGE_VERBS.get(verb)
                if prefix is None or not action.name.startswith(f"{prefix}_"):
                    wrong.append(f"{spec.name}.edge_audit {verb!r}: {action.name}")
        for axis in spec.state_axes:
            if not axis.action.name.startswith(f"{_STATE_AXIS_VERB}_"):
                wrong.append(f"{spec.name} state axis: {axis.action.name}")
    assert not wrong, f"Spec audit actions use the wrong verb for their shape: {wrong}"
