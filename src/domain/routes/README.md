# Routes

Thin HTTP adapters. One route file per resource. CRUD-shaped routes declare an `EntitySpec` in [`../specs/`](../specs/) and call `mount_entity(router, ENTITY, handlers={...})`; the dispatcher reads the spec and fires the right `mount_*` helper for each opted-in verb.

The URL shape, lifecycle, and subresource conventions every resource MUST follow live in [`RESOURCE_GRAMMAR.md`](RESOURCE_GRAMMAR.md). The dispatcher contract lives in [`../../framework/dispatch/README.md`](../../framework/dispatch/README.md). This file documents only what's specific to this directory.

## Adding a CRUD resource

1. Declare the spec in [`../specs/<entity>.py`](../specs/) with a colocated `test_<entity>.py`, and add it to the `ALL_ENTITY_SPECS` re-export in [`../specs/__init__.py`](../specs/__init__.py).
2. Create `<entity>.py` here. Call `register_entity(<ENTITY>_ENTITY)` (returns a `BaseRouter`) and `mount_entity(...)`. The `register_entity` call wraps `make_entity_router` and appends `(spec, router)` to the framework's [`entity_registry`](../../framework/dispatch/registry.py) — `main.py` iterates that registry once, so there is no per-entity `include_router(...)` line to add.
3. Add the new module to the import list in [`__init__.py`](__init__.py); the explicit imports are what trigger the `register_entity` side effect.
4. Add `test_<entity>.py` for resource-specific behavior (the framework verbs are already covered under [`../../framework/dispatch/`](../../framework/dispatch/)).

```python
from src.domain.specs.<entity> import <ENTITY>_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(<ENTITY>_ENTITY)

mount_entity(router, <ENTITY>_ENTITY)
```

## Sub-resources

Declare the child entity with `parent=PARENT_ENTITY` on its spec; pass it through `owned_subentities=` on the parent's `mount_entity` call. Each opted-in verb on the child auto-binds `make_<verb>_handler(child)`; supply `handlers["<child.name>.<verb>"]` only when the child needs a bespoke handler.

## Bespoke routes

The grammar fits resource-shaped CRUD. These stay hand-written. A hand-written *family* (several modules serving one concern) lives in a subpackage — `auth/` (login/register/verify flow) and `dev/` (development-only routes, mounted iff `ENVIRONMENT == "development"`) — while single-file bespoke routes stay at the top level next to the entity route files:

| Route(s) | File | Reason |
|---|---|---|
| `POST /auth/register` | `auth/auth_routes.py` | Auth-flow protocol (token issuance, fastapi-users hooks). |
| `GET /auth/{register,login,forgot-password,reset-password/{token}}` | `auth/auth_pages.py` | Pure form rendering. |
| `GET /users/me`, `GET /users/me/clinicians` | `users.py` | Singleton aliases — mounted via `singleton_alias=` on the existing `mount_detail` / `mount_related_list`. |
| `POST/DELETE /users/me/favorites/{clinician_id}` | `favorites.py` | M:N edge add/remove toggle via `mount_edge_routes` (no `list_handler` → no list page; favorited clinicians are browsed via `/clinicians?favorited=me`). |
| `POST /posts/{post_id}/message` | `posts.py` | Event endpoint (emails the post owner). The sender's first message also creates their `PostConnection` edge, and every send writes a `send_post_message` audit event against it (the per-message history; the body is never stored) — the edge has no routes of its own because it is create-only (no disconnect) and only ever born from a sent message. |
| `GET /users/me/access`, `GET /users/me/access/capabilities/{name}` | `access.py` | Derived read view — capability posture, no stored row. |
| `GET /users/me/email/form` | `user_email.py` | Email field-cluster subresource form — self-only; surfaces verification status, hosts the unverified-viewer / post-resend inbox CTA, and the resend-verification action. |
| `GET /admin/audit` | `admin.py` | Derived read view over the framework-owned audit log — superuser-only, paginated, no stored resource. |
| `GET /`, `GET /health` | `../../main.py` | Utility endpoints. |

## Tests

Colocated `test_<resource>.py`. Shared fixtures from [`../../../tests/fixtures.py`](../../../tests/fixtures.py); user helpers from [`../../../tests/helpers.py`](../../../tests/helpers.py). Contract pairs for HTML forms and htmx-driven actions live in [`../../../tests/test_contract/`](../../../tests/test_contract/README.md) — required per the [grammar](RESOURCE_GRAMMAR.md).
