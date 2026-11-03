"""Seed orchestrator — walks `metadata.sorted_tables` in FK-safe order
and, per table, either runs a registered override or generates rows
generically via `build_row`.

Two design moves keep "adding a model" cheap:

  1. **FK-safe ordering is derived, not declared.** SQLAlchemy already
     knows the topological order from FK declarations; we just walk it.
     Adding a model means SQLAlchemy puts it in the right place — no
     edit here.

  2. **Generic-by-default, override-by-exception.** A model with no
     entry in `overrides.OVERRIDES` falls through to introspection-
     driven `build_row` for `GENERIC_COUNTS.get(table, DEFAULT)` rows.
     Adding a normal model is zero edits anywhere (besides the model
     file itself).

Tables the runner *deliberately* skips:
  - `audit_log` — framework-owned; AuditLog appends rows in response to
    other writes, so seeding it directly would be redundant and would
    fight the trigger semantics.

Tables added in the future that need a row count: add an entry to
`counts.GENERIC_COUNTS`. The runner default is intentionally small
(`DEFAULT_GENERIC_COUNT`) so unknown tables don't explode the seed.
"""

from __future__ import annotations

import asyncio
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from src.db import async_session_maker
from src.domain.models import metadata
from src.framework.persistence.base_model import Base

from . import counts
from .generators import SeedPool, build_row
from .overrides import OVERRIDES
from .rng import SeededRandom, deterministic_uuid

# Tables that should NOT be seeded by the runner. `audit_log` lives
# in `src/framework/audit/log.py` and is written by triggers/handlers
# elsewhere — directly seeding rows would duplicate the audit trail
# the rest of the seed already implicitly produces.
SKIP_TABLES: Final[frozenset[str]] = frozenset({"audit_log"})

# Tables that need a second pass because their override depends on
# rows that `metadata.sorted_tables` doesn't FK-order against them.
# `posts` has no FK to `clinicians` or `programs`, but its `OpeningDetail`
# / `IntakeDetail` children do — so the Post override has to run AFTER
# everything else, not in FK-topological order. Any table whose
# override reads seeded posts from the pool (e.g. `post_connections`)
# must follow `posts` here. Listed in the order the post-pass should
# execute.
POST_PASS_TABLES: Final[tuple[str, ...]] = (
    "posts",
    "referral_details",
    "opening_details",
    "intake_details",
    "post_connections",
)

# Generic-pathway row counts for tables that DON'T have an override.
# Default applies if a new table appears without an entry.
DEFAULT_GENERIC_COUNT: Final[int] = 10
GENERIC_COUNTS: Final[dict[str, int]] = {
    "programs": counts.PROGRAM_COUNT,
}


def _model_for_table(table_name: str) -> type | None:
    """Look up the mapped class for a given table name. Returns None
    for tables with no mapped class (e.g. pure-association tables);
    those are skipped by the runner."""
    for mapper in Base.registry.mappers:
        if mapper.local_table.name == table_name:
            return mapper.class_
    return None


async def _seed_table(
    table_name: str,
    rng: SeededRandom,
    pool: SeedPool,
    session: AsyncSession,
) -> int:
    """Seed one table; record rows in pool; return created/seen count."""
    if table_name in SKIP_TABLES:
        return 0

    model = _model_for_table(table_name)
    if model is None:
        # No mapped class — skip silently (e.g. raw association tables
        # SQLAlchemy declared without a class). Coverage is the lint's
        # job to flag if this happens unexpectedly.
        return 0

    if model in OVERRIDES:
        rows = await OVERRIDES[model](rng, pool, session)
        pool.add(table_name, rows)
        print(f"  ✅ {model.__name__:>26}  {len(rows):>4} rows (override)")
        return len(rows)

    # Generic introspection-driven path.
    target = GENERIC_COUNTS.get(table_name, DEFAULT_GENERIC_COUNT)
    rows = []
    for i in range(target):
        row = build_row(model, i, rng, pool)
        merged = await session.merge(row)
        rows.append(merged)
    await session.commit()
    pool.add(table_name, rows)
    print(f"  ✅ {model.__name__:>26}  {len(rows):>4} rows (generic)")
    return len(rows)


async def seed_all() -> int:
    """Orchestrator entry point. Returns process exit code (0 on success)."""
    rng = SeededRandom()
    pool = SeedPool()
    total = 0
    print("🌱 Seeding (deterministic, ~500 rows, idempotent re-runs)…")
    async with async_session_maker() as session:
        # Phase 1: FK-topological walk, skipping post-pass tables.
        for table in metadata.sorted_tables:
            if table.name in POST_PASS_TABLES:
                continue
            total += await _seed_table(table.name, rng, pool, session)
        # Phase 2: deferred tables whose override depends on rows the
        # FK graph doesn't force-order against them — anything that
        # needs seeded posts in the pool (see `POST_PASS_TABLES`).
        for table_name in POST_PASS_TABLES:
            total += await _seed_table(table_name, rng, pool, session)
    print(
        f"\n✅ Seed complete — {total} rows across {len(metadata.sorted_tables)} tables."
    )
    print(
        "   Login: admin@example.com or any /dev/login-as persona  (password: password)"
    )
    return 0


def main() -> int:
    return asyncio.run(seed_all())


# Mark `deterministic_uuid` as re-exported so callers can reach it
# without dipping into `rng` directly.
__all__ = ["seed_all", "main", "deterministic_uuid"]
