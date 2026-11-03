# Audit: append-only mutation record

Append-only mutation record per [`../../domain/routes/RESOURCE_GRAMMAR.md`](../../domain/routes/RESOURCE_GRAMMAR.md). Every mutation handler MUST write an audit row in the same transaction as the mutation; the `test_audit_discipline.py` static check enforces this at CI time.

## The contract

Every mutation handler does one of:

```python
# Option 1: bare helper, used by non-CRUD mutations (register, set-activation).
await record_audit(audit_repo, actor_id=..., resource_type=..., resource_id=...,
                   action=..., before=..., after=...)
await repo.session.commit()

# Option 2: resource-flavored helper for handlers that don't fit the
# snapshot/mutate/audit/commit ritual.
await record_audit_for(audit_repo, actor=..., target=..., resource=R, verb="update")
await repo.session.commit()

# Option 3: the context manager that owns the whole ritual.
async with mutate(repo, audit_repo, actor=..., target=..., resource=R, verb="update"):
    await repo.update_X(target, ...)
```

The discipline check accepts any of the three. If a handler `commit`s without one of those names appearing in its body, the test fails with a pointer to RESOURCE_GRAMMAR.md.

## Files

- `core.py` — `AuditAction` enum, `AuditedResource` / `EdgeAudit` dataclasses, `record_audit`, `record_audit_for`, the `mutate(...)` context manager, `make_audited_resource(...)` factory, `make_snapshotter(...)`.
- `log.py` — the `AuditLog` SQLAlchemy model (append-only; FK to `users.id` with `SET NULL`; `(resource_type, resource_id)` lookups).
- `repository.py` — `AuditRepository`, deliberately exposing only writes + reads (`list_for_resource`, the newest-first `list_all` behind the superuser-only `/admin/audit` viewer in `src/domain/routes/admin.py`). No `update_*` / `delete_*` — audit rows are immutable.

## `AuditAction` naming

Member names are `<VERB>_<RESOURCE>` and values are the lowercased name (`ADD_FAVORITE = "add_favorite"`). The verb comes from the resource's audit shape:

| Shape | Verbs | Declared by |
|---|---|---|
| CRUD entity | `CREATE_` / `UPDATE_` / `DELETE_` — always the full triple | `EntitySpec.audit` (`make_audited_resource`) |
| Edge (M:N join, immutable rows) | `ADD_` / `REMOVE_` | `EntitySpec.edge_audit`, or a `_BESPOKE` edge with no spec |
| State axis (flip one field without a full PUT) | `SET_` | `EntitySpec.state_axes` |
| Event (no resource is mutated) | a bare event name, e.g. `REGISTER`, `JOB_RUN_STARTED` | `_EVENT_ACTIONS` in `test_audit_action_drift.py` |

Pick the verb from the shape, not from what the user did: the first message about a post creates a `PostConnection` edge, so it is `ADD_POST_CONNECTION`, not `CONNECT_POST`. Never use a lone `CREATE_` for something that isn't a CRUD triple. Values are persisted forever, so a misnamed member is permanent; `test_audit_action_drift.py` enforces this table.

## System actor

Writes that aren't driven by a request (scheduled jobs, system-triggered runs) pass `actor_id=None`. `AuditLog.actor_id` is `nullable=True` with `ON DELETE SET NULL` (see [`log.py`](log.py)), so the row outlives any specific user.

## The discipline check

`test_audit_discipline.py` parses each `handlers.py` under `src/domain/` (recursively), walks every `async def handle_*` function, and fails the test if the function calls `.commit()` without an audit-recording call. Opt-out: add `audit-discipline-ignore` to the function's docstring with a brief reason. Use sparingly.

## Tests

`test_core.py`, `test_repository.py`, `test_audit_discipline.py`, `test_audit_action_drift.py` (asserts every `AuditAction` member is justified by a spec or the bespoke allow-list, and follows the naming grammar above).
