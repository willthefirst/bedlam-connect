# `scripts/dev/seed/` — deterministic, introspection-driven dev seed

Run via `dev seed`. Produces ~500 rows across every domain table,
deterministically (same data every run), idempotently (re-running is a
no-op via `session.merge` on stable PKs).

## How extension works

This package is structured so that **adding a model usually requires
zero edits here**. The runner walks `metadata.sorted_tables` in
FK-safe order and, per table, either:

  1. Runs a registered override (`overrides/*.py`), or
  2. Falls through to the generic introspection-driven generator
     (`generators.py::build_row`), which decides each column's value
     from CHECK constraints, JSON-list sources, column-name vocab, and
     type defaults.

When you change a model, the right action depends on what changed:

| Change | What you do here |
| --- | --- |
| Add a CHECK-bound Text column (`Text + named_check_in`) | Nothing. `check_registry.py` parses the CHECK SQL; the generator round-robins the values. |
| Add a Bool / Date / Int / Float / DateTime / UUID column | Nothing. Type-based defaults in `generators.py` cover it. |
| Add a FK column | Nothing. The generator picks a random row from the FK target table. |
| Add a JSON list column referencing an enum | Add one line to `vocab.JSON_LIST_SOURCE`. |
| Add a JSON object column (default `dict`) | Nothing. The generator seeds `{}`; the drift lint treats a `dict`-default JSON column as covered. |
| Add a free-text column with a domain-meaningful name (`institution`, `cost`, `slogan`) | Add one line to `vocab.COLUMN_VOCAB`. |
| Add a free-text column where `<name>_<NN>` placeholder is OK | Add the name to `vocab.PLACEHOLDER_OK`. |
| Add a model with structural specials (constructor side effects, hierarchy, fan-out, M:N) | Create a new module under `overrides/` and `@register(YourModel)`. |
| Add a non-`IN` CHECK (e.g. a cardinality `json_array_length(col) <= 1`) on an **override-owned** table | Nothing extra here — the override already produces CHECK-valid rows, so the drift lint skips it. Make sure your override writes values that satisfy the CHECK. |
| Change row counts | Edit `counts.py`. |

The drift lint (`lint_coverage.py`, wired into `dev lint`) hard-fails
on uncovered Text columns and unresolved CHECKs — so the table above
is enforced, not just documented. If you forget a step, lint tells
you the exact one-line fix. Tables an `overrides/` module owns
end-to-end are exempt from the unresolved-CHECK rule: the generic
generator never inserts them, so the override (not the lint) is what
guarantees CHECK-valid rows.

## Layout

```
scripts/dev/seed/
├── __init__.py         # re-exports `main`, `seed_all`
├── __main__.py         # `python -m scripts.dev.seed` entry
├── README.md           # this file
├── rng.py              # SeededRandom (fixed seed) + deterministic_uuid
├── vocab.py            # COLUMN_VOCAB / PLACEHOLDER_OK / JSON_LIST_SOURCE
├── check_registry.py   # parses CHECK SQL → allowed-values tuple
├── generators.py       # generic introspection-driven row builder
├── counts.py           # per-entity row-count targets
├── runner.py           # orchestrator (walks metadata.sorted_tables)
├── lint_coverage.py    # `dev lint` drift detection (hard-fail)
└── overrides/          # per-model structural specials
    ├── __init__.py     # OVERRIDES registry + @register decorator
    ├── users.py        # fastapi-users password hashing
    ├── organizations.py # parent/child hierarchy
    ├── clinicians.py   # Clinician + ClinicianAffiliation
    ├── credentials.py  # 1-3 per clinician fan-out
    ├── posts.py        # kind discriminator + matching detail
    ├── post_connections.py # M:N dedup, no self-connections (post-pass)
    ├── verifications.py # one per selected clinician
    └── favorites.py    # M:N dedup
```

## Determinism

`rng.SEED = 20260522` is the seed. Same input → same data, every run.
`deterministic_uuid(model_name, index, ...)` produces stable PKs so
`session.merge` upserts the same row on rerun. Bump the seed only when
you deliberately want a new dataset; downstream visual-regression
tests will drift.

## Why this design

The previous `scripts/dev/seed.py` hand-coded 1900 lines of fixture
literals. Two problems:

  - **Coverage gaps.** Only a sliver of the enum space appeared
    (51 US_STATES → 2-3 in practice; 11 INSURANCE_CARRIERS → 4; etc.).
    Empty-state UI cases never had matching rows. The auto-discovering
    test in `test_seed.py` proves the new generator hits every CHECK
    value and every nullable column's both sides.
  - **Drift.** Every model change required a manual fixture edit; if
    you forgot, the seed silently didn't cover the new column. The
    drift lint here forces the choice at PR time — no silent gaps.

## Login credentials

The pinned anchor accounts:

  - `admin@example.com` (`is_superuser=True`) — muscle-memory admin.
  - Three **persona** anchors — one per auth state the rest of the
    app branches on. The registry is the single source of truth at
    [`src/domain/routes/dev/dev_personas.py`](../../../src/domain/routes/dev/dev_personas.py)
    and the dev login dropdown
    ([`src/domain/routes/dev/dev_auth.py:DEV_SEED_USERS`](../../../src/domain/routes/dev/dev_auth.py))
    reads from it:

      - `unverified@example.com` — `User.is_verified=False`, no anchor
        Clinician.
      - `clinician-pending@example.com` — email verified, owns a
        Clinician with `clinician_verified=False`.
      - `clinician-verified@example.com` — email verified, owns a
        Clinician with `clinician_verified=True`.

Password for every seeded user: `password`. Visiting
`/dev/login-as-seed-user` (dev-only route) signs in as the admin;
`/dev/login-as?email=<addr>` (also dev-only) signs in as any seeded
user — that's what the login-page dropdown wires up.

## Dev-only magic NPI

In `ENVIRONMENT=development`, submitting `0000000000` as a clinician's
NPI short-circuits the NPPES lookup in
[`src/domain/logic/verifications/handlers.py`](../../../src/domain/logic/verifications/handlers.py)
and produces a synthetic "verified" Verification row against the
clinician's own name. Lets local devs and Playwright/MCP automation
walk the verified-clinician flow without hitting the public NPPES API.
Never honored outside development — gated by the same
`settings.ENVIRONMENT == "development"` check that mounts
`/dev/login-as`.
