"""Per-model structural overrides.

The generic introspection-driven generator in `../generators.py` covers
single-row-from-columns shapes. This package owns the cases that need
something more:

  - Cross-row construction (Post + matching kind-detail).
  - Owner assignment and fan-out (Clinician + ClinicianAffiliation).
  - Fan-out counts that depend on other rows (1-3 credentials per clinician).
  - Hierarchical structure (parent/child Organizations).
  - Special creation paths (User → fastapi-users password hashing).
  - M:N dedup (UserFavorite).

Adding a new model: if the generic generator handles it, you do
nothing here. Add an override only when the model needs something the
generic path can't reasonably introspect.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from src.framework.persistence.base_model import BaseModel

# Override signature: takes (rng, pool, session) and returns the rows it
# added. The runner adds those rows to the pool so downstream
# generators can FK to them. Overrides are responsible for their own
# idempotency (deterministic IDs + `session.merge` or
# get-or-create).
OverrideFn = Callable[
    ["SeededRandom", "SeedPool", "AsyncSession"],
    Awaitable[list[BaseModel]],
]


# Populated by the per-model modules below at import time via @register.
OVERRIDES: dict[type[BaseModel], OverrideFn] = {}


def register(model: type[BaseModel]):
    def decorator(fn: OverrideFn) -> OverrideFn:
        OVERRIDES[model] = fn
        return fn

    return decorator


# Import side effects: each module @register's against OVERRIDES.
from . import (  # noqa: E402,F401
    admin_notes,
    clinicians,
    credentials,
    favorites,
    org_representations,
    organizations,
    post_connections,
    posts,
    programs,
    saved_searches,
    users,
    verifications,
)


def has_override(model: type[BaseModel]) -> bool:
    return model in OVERRIDES
