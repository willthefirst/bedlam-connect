# Programs cluster

The SQLAlchemy model for the `programs` table. A :class:`Program` is a treatment offering owned by an :class:`Organization` — distinct from :class:`Clinician`. PR 4 of the Org/Program roadmap (#537).

The model file's own docstring documents the column-level grammar (ownership, `state_preference` independence from the parent Org, no insurance fields). This README captures only the cross-file ties that aren't visible from inside `program.py`:

- **Reverse FKs** — :class:`Program` is referenced from:
  - A Clinician's Org link lives on :class:`ClinicianAffiliation.org_id`, not on the Program — Clinicians attach to Orgs (via their affiliation), not Programs (the Program is the intake door; the Clinician does the clinical work).
  - :class:`IntakeDetail.program_id` (#541) — posts of kind `program_intake` announce a Program's intake openings. `program.intake_details` back-populates the relationship. Deleting a Program cascades through to its intake posts (a post about a deleted Program is stale by construction).

- **Form / authz wiring** — Program edits go through the framework's factory-built `mount_entity`; the `payload_authz_path` declared on `PROGRAM_ENTITY` enforces "the user may only attach a Program to an Org they own" (#537). The intake post create flow has its own `payload_authz` check on `POST_ENTITY` (#541) enforcing "the user may only post Program-availability for a Program they own" — same shape, different entity boundary.

- **Repository hook** — :class:`ProgramRepository.list_for_user` (#541) returns the requesting user's owned Programs, newest first; consumed by `User.programs` (eager `selectin` reverse FK) which the intake form's Program picker reads via `program_options` ([`../../logic/posts/view.py`](../../logic/posts/view.py)) — the viewer's programs on create, the post owner's on edit.

## Steady-state context

The Program is the durable-entity side of the [steady-state split](../README.md#steady-state-context-vs-per-announcement-dimensions): it holds only what doesn't vary intake-to-intake — name / description, `state_preference`, the intake window (`start_date` / `end_date`), `accepting_referrals` posture, `languages`, how to refer (`website` / `referral_instructions`), the owning Org link, and the denormalized `currently_accepting_new_patients` cache.

The per-announcement **profile** (service lines, the cohort served, cost) lives on the intake post, not here — a Program can post two intakes targeting different cohorts or service lines, so those dimensions are per-announcement. They moved onto `IntakeDetail`, which is now self-describing on the single `ReferralService` "what care" vocabulary; see [`../posts/README.md`](../posts/README.md). This mirrors the opening side, where the same dimensions live on `OpeningDetail` and `ClinicianAffiliation` carries only context — see [`../clinician_affiliations/README.md`](../clinician_affiliations/README.md). The view layer (`src/domain/logic/posts/view.py`) reads each axis from its single home: per-announcement fields off the intake detail, steady-state context off this Program row.

The Program edit/new forms (`src/domain/templates/programs/_form_new_fragment.html` and `form_edit.html`) collect the context fields directly; the detail page (`detail.html`) renders them as facts rows. The wire schemas (`src/domain/logic/programs/schema.py`) accept them on `ProgramCreate` / `ProgramUpdate` and surface them on `ProgramRead`.

Note that `languages` belongs on the Program directly (not on a person) — a Program is the offering, and which languages it covers is an attribute of the offering itself; this is the intake side's program-level `languages` home (the opening side keeps `languages` on the person, `Clinician`). `currently_accepting_new_patients` is distinct from the `accepting_referrals` flag: `accepting_referrals` is the operator's standing posture ("we generally take referrals"), while `currently_accepting_new_patients` is the cached "we have an active intake right now" signal toggled by the `IntakeDetail` lifecycle.
