# Posts cluster: parent + per-kind detail models

This subdirectory holds the SQLAlchemy models for the `posts` table and its per-kind detail tables, plus the registry that ties them together. The parent layer's conventions (BaseModel inheritance, FK-relationship coverage, migration workflow) live in [`../README.md`](../README.md); this README covers what's specific to the posts cluster.

## Files

- `post.py` — `Post`, the parent table for any post-shaped resource. Carries identity, ownership, timestamps, and the `kind` discriminator. The `ck_posts_kind` CHECK constraint is rendered from `POST_KINDS.check_sql()` in `post_kinds.py`. Adding a kind means adding a registry entry and a `relationship(...)` line to `Post`.
- `post_kinds.py` — `POST_KINDS: DiscriminatorRegistry[PostKindSpec]`, the single source of truth for the kind set. Each `PostKindSpec` records the kind name, its detail-model class, the relationship attribute on `Post`, the detail row's user-facing field tuple (derived from the model's columns via `_detail_fields(model)`), the create/edit template paths, the canonical capital-case `noun` (the SOT for "what is this kind called" everywhere the user reads it — picker headings, /posts sidebar `kind` filter options, every "Create X" / "Edit X" page H1 and CTA), and the one-line `picker_description` tagline shown under the noun on /posts/form. The registry's bookkeeping (`names` tuple, `check_sql()`, reverse indexes) comes from the generic `DiscriminatorRegistry` in [`src/framework/persistence/polymorphic.py`](../../../framework/persistence/polymorphic.py); this file declares only the post-specific Spec shape and the registry instance. Every cross-cutting site reads from this registry — see [`../README.md` § "The `post_kinds` registry"](../README.md#the-post_kinds-registry) for the full list.
- `referral_detail.py` — `ReferralDetail`, the detail row for `kind='referral'`. 1:1 with `posts` via `post_id` (PK + FK with CASCADE). Columns track the client-referral intake form; enum columns CHECK against tuples in [`../enums.py`](../enums.py); the `services`, `insurance_carriers`, and `languages` JSON multi-selects have their vocabularies enforced on the wire by Pydantic (no SQL CHECK against array members). The `age_groups` JSON column is the one exception that carries a SQL CHECK — not on *membership* but on *cardinality*: `ck_referral_details_age_groups_single` (`json_array_length(age_groups) <= 1`) because a referral describes a single client (exactly one bucket; the form renders a single `<select>` and the wire's `RequiredAgeGroupsField` is `min_length=1, max_length=1`). This is the *referral* sense of `age_groups` (single bucket); an opening's and an intake's `age_groups` are multi-valued (on `OpeningDetail` / `IntakeDetail` themselves, since each serves a cohort). (The earlier `desired_times`, `affirming_identities`, `acceptable_license_types`, and `clinical_niches` columns were dropped in migration `606967b5ec1f`; older `audit_log` snapshots may still carry them.) The `(city, state)` pair is declared **inline** (explicit `Text` columns, no ZIP) — a referral targets a city or area, not a postal address, so it does *not* use [`LocationMixin`](../../../framework/persistence/mixins.py). The `<field>_other_text` free-text columns (`services_other_text`, `insurance_carriers_other_text`, `languages_other_text`, `pronouns_other_text`) and the in-person `location_city` are **conditionally required** — the one home for which field is required-when is [`../../logic/posts/conditional_fields.py`](../../logic/posts/conditional_fields.py), which drives both the server-side validation (field-targeted 422s) and the form's pure-CSS `:has()` reveal. No SQL CHECK enforces these (the dependency is cross-field).
- `opening_detail.py` — `OpeningDetail`, the detail row for `kind='clinician_opening'`. **Self-describing announcement**: it carries its own per-announcement dimensions — delivery format (`session_format`), service lines (`services` / `services_other_text`, on the same `ReferralService` 12-leaf vocabulary the referral request side uses), the cohort it's for (`age_groups`, multi-valued — an opening serves a cohort, unlike referral's single-client cardinality CHECK — and `genders`), and `cost` — plus the announcement core (`schedule_text` / `description`) and the two context FKs (`clinician_id`, `clinician_affiliation_id`). The remodel **reversed** the #1358 PR-f split for these dimensions: they're per-announcement, not per-affiliation, so a clinician can post two openings under the same affiliation targeting different cohorts/formats. The headline is derived from the linked practice's org name (no custom `subject` override), aligning with the referral model. Only the steady-state context (location, insurance posture, `website` / `referral_instructions`, `currently_accepting_new_patients`) lives on the linked `ClinicianAffiliation` — see [`../clinician_affiliations/README.md`](../clinician_affiliations/README.md); `languages` lives on the linked `Clinician`. Table name stays `opening_details` from before the kind rename (migration `9e1f7b3c4a2d`) — pure rename noise to drop it.
- `intake_detail.py` — `IntakeDetail`, the detail row for `kind='program_intake'` (#541). **Self-describing announcement**, mirroring `OpeningDetail`: it carries its own per-announcement dimensions — service lines (`services` / `services_other_text`, on the same `ReferralService` 12-leaf vocabulary the referral and opening sides use), the cohort it serves (`age_groups`, multi-valued — an intake serves a cohort, unlike referral's single-client cardinality CHECK — and `genders`), and `cost` — plus the announcement core (`schedule_text` / `description`) and the single Program context FK (`program_id`). It carries **no** `session_format` — a Program is a single group offering with no per-announcement in-person/virtual axis. A Program can post two intakes targeting different cohorts or service lines, so those dimensions are per-announcement, not per-program. Only the steady-state context (Program name, `state_preference`, intake window, `languages` — program-level, since the intake side has no person — `website` / `referral_instructions`, owning Org) lives on the linked `Program` — see [`../programs/README.md`](../programs/README.md). The headline is derived from the program name (no `subject` override). Table name stays `intake_details` for the same reason as `opening_details`.

### Listing context (`clinician_affiliation_id`)

The two clinician-authored detail kinds (`OpeningDetail`, `ReferralDetail`) carry a nullable `clinician_affiliation_id` FK → `clinician_affiliations.id` (`ON DELETE SET NULL`): a clinician who affiliates with several orgs (`clinician_affiliations` is 1:N off `clinicians`) declares *which* affiliation a given opening/referral is offered under. It's nullable because the column post-dates existing rows and because not every listing has a context set. `IntakeDetail` has no such column — its context is the `Program`'s owning org, reachable via `program_id`. Migration `c4d5e6f7a8b9` added the columns and backfilled each existing row to its clinician's primary (earliest-`created_at`) affiliation, matching `Clinician.primary_clinician_affiliation`.

On the create/edit forms this column is the **only** clinician selector the user touches: the practice picker submits `clinician_affiliation_id`, and the listing's clinician FK (`referring_clinician_id` for referrals, `clinician_id` for openings) is *derived* from that affiliation server-side — so the two can never disagree, and a clinician affiliated with two orgs no longer collapses both options onto one value. The derivation runs in `_resolve_affiliation_context` ([`../../logic/posts/handlers.py`](../../logic/posts/handlers.py)) before the FK-ownership check, which then validates the resolved clinician.

Because the affiliation *is* the clinician↔org link, it also carries the **org-rep authority chain** on create: `_assert_post_payload_authz` authorizes a referral/opening either via the **self** path (own the resolved clinician + hold Claim A) or the **org-rep** path (be a verified `OrgRepresentation` — Claim B — for the affiliation's org, per `capabilities.org_rep_verified`). The org-rep path lets a group-practice coordinator post under an affiliated clinician they don't own without holding Claim A. It's wired on **create only**: editing a post one doesn't own is still gated by the object-level owner-or-admin `write_authz` that runs before the payload hook on PATCH (expanding that to the org-rep chain needs an async object-level policy — a separate change).

## Kind name history (audit-log readers)

Audit-log rows persist the kind value that was current when the row was written. Two renames happened in `posts.kind`:

| Migration | Old value | New value |
|---|---|---|
| `e9d8c7b6a5f4` | `provider_availability` | `opening` |
| `e9d8c7b6a5f4` | `client_referral` | `referral` |
| `4a8b2c5d9e1f` | `program_availability` | `intake` |
| `9e1f7b3c4a2d` | `opening` | `clinician_opening` |
| `9e1f7b3c4a2d` | `intake` | `program_intake` |

`audit_log.before` / `audit_log.after` JSON snapshots reference whatever string was current when the row was written; they are intentionally not rewritten. Readers ranging over audit history should expect any of the historical names.
- `test_post_kinds.py` — guardrail tests for the registry as the single source of truth. Asserts `POST_KIND_NAMES` matches the registry, the rendered `POST_KINDS.check_sql()` matches what `Post.__table_args__` actually produces, the route's `Literal[*POST_KIND_NAMES]` is in lockstep, the inverse `POST_KIND_BY_DETAIL_MODEL` lookup is well-formed, the per-kind relationship-name convention holds, and `PostKindSpec.detail_fields` matches the detail-model column list exactly. If anyone re-encodes the kind set inline somewhere, one of these tests fails.

## Why this cluster, not flat siblings

Before this extraction, `post.py`, `post_kinds.py`, and the two detail files lived alongside the former `provider.py` and credential files as siblings of one flat `src/domain/models/`. They formed a cluster the directory didn't reflect:

- `post.py` imports from `post_kinds.py`.
- `post_kinds.py` imports from `referral_detail.py` and `opening_detail.py`.
- The two detail files share a common table-CHECK pattern, both depend on the same `enums.py` vocabularies.

Pulling them into `posts/` makes the boundary explicit: a reader landing here finds the entire posts data model in one place. Cross-domain shared modules (the controlled-vocabulary tuples in `../enums.py`, the `BaseModel` in [`src/framework/persistence/base_model.py`](../../../framework/persistence/base_model.py)) stay at the parent level because they're consumed by the clinicians cluster too.

## Adding a new kind

The full cross-layer recipe lives in [`src/README.md`](../../../README.md#adding-a-new-domain-entity); the model-layer steps for a new kind are:

1. Add a new detail model file `<kind>_detail.py` in this directory. Follow the shape of `referral_detail.py`: 1:1 with `posts` via `post_id` PK+FK with CASCADE, enum columns CHECK against tuples in `../enums.py` via `check_in_tuple_sql`.
2. Add a `relationship("<KindDetail>", uselist=False, cascade="all, delete-orphan", lazy="selectin")` line on `Post` in `post.py`.
3. Add a `PostKindSpec` entry to `POST_KINDS` in `post_kinds.py`. The `detail_fields` tuple is derived from the model's columns automatically; you only supply the name, detail class, relationship attribute, label, and template paths.
4. Re-export the new detail class from `../__init__.py`.
5. Generate an Alembic migration for the new detail table and the widened `posts.kind` CHECK.

The remaining layers (Pydantic schemas, repository dispatch, logic handlers, route Literal, templates) are all registry-driven — `test_post_kinds.py` will fail loudly if any of them drifts from `POST_KINDS`.

## Removing a kind

Inverse: delete the registry entry, the detail model file, the `relationship(...)` line on `Post`, the four Pydantic variant classes in `src/domain/logic/posts/schema.py`, the per-kind templates (all per-kind templates live directly under `src/domain/templates/posts/` following the default `PostKindSpec` convention — no template path overrides), and ship a migration that drops the detail table and narrows the CHECK. No edits in routes, repositories, or logic — see [`../../routes/posts.py`](../../routes/posts.py) and the per-kind schema in [`../../logic/posts/schema.py`](../../logic/posts/schema.py); both read from the registry. The retired `note` kind (removed in migration `c2d3e4f5a6b7`) is the canonical example of how clean this is when the registry is the only source of truth.

## URL faces

A single URL family exposes the supertype:

- **`/posts`** — whole-supertype face listing every kind (`kind ∈ {referral, clinician_opening, program_intake}`). The `?kind=X` query param narrows the list and drives create/edit dispatch to the per-kind detail model and template. Spec: `POST_ENTITY`. See [`src/framework/dispatch/entity_spec.py`](../../../framework/dispatch/entity_spec.py) `discriminator_value` docstring for the face-mode contract.

The previous per-face URL families (`/referrals`, `/openings`, `/intakes`) were collapsed into the single `/posts` face; the kind values survive unchanged, only the URL collection changed.
