"""add admin_notes and observability views

Revision ID: 37ea65ccbf12
Revises: 9bab6e514e4b
Create Date: 2026-11-02 21:23:24.289868

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "37ea65ccbf12"
down_revision: Union[str, None] = "9bab6e514e4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Observability views read by the admin's Datasette saved queries
# (`src/domain/logic/admin_data/metadata.yaml`). The app never queries them. They
# live only here — tests build them by running the migrations — so the
# SQL is frozen with this revision; changing a view later is a new
# migration that drops and recreates it.
#
# Timestamps are UTC text (`YYYY-MM-DD HH:MM:SS[.ffffff]`), so every
# comparison goes through `julianday()`, never a raw string compare.
# Insertion order matters: later views read earlier ones.
_VIEWS: dict[str, str] = {
    # One display name per user: their first clinician's name, falling
    # back to the username (users have no name column).
    "member_names": """
        SELECT
            u.id AS user_id,
            COALESCE(
                (
                    SELECT c.first_name || ' ' || c.last_name
                    FROM clinicians c
                    WHERE c.owner_id = u.id
                    ORDER BY c.created_at
                    LIMIT 1
                ),
                u.username
            ) AS name,
            u.email AS email
        FROM users u
    """,
    # One title per post, e.g. "Referral: adults_25_64, therapy_individual,
    # kaiser". Vocabulary tokens stay raw — labels live in Python
    # (`src/domain/models/enums.py`), which SQL can't reach.
    "post_summaries": """
        SELECT
            p.id AS post_id,
            p.owner_id AS owner_id,
            p.kind AS kind,
            p.created_at AS created_at,
            CASE p.kind
                WHEN 'referral' THEN 'Referral: ' || COALESCE(
                    NULLIF(
                        trim(
                            COALESCE(json_extract(r.age_groups, '$[0]'), '')
                            || COALESCE(', ' || (SELECT group_concat(value, ', ') FROM json_each(r.services)), '')
                            || COALESCE(', ' || (SELECT group_concat(value, ', ') FROM json_each(r.insurance_carriers)), ''),
                            ', '
                        ),
                        ''
                    ),
                    'no details'
                )
                WHEN 'clinician_opening' THEN 'Opening: ' || COALESCE(org.name, 'practice')
                WHEN 'program_intake' THEN 'Intake: ' || COALESCE(pr.name, 'program')
                ELSE p.kind
            END AS title
        FROM posts p
        LEFT JOIN referral_details r ON r.post_id = p.id
        LEFT JOIN opening_details o ON o.post_id = p.id
        LEFT JOIN clinician_affiliations ca ON ca.id = o.clinician_affiliation_id
        LEFT JOIN organizations org ON org.id = ca.org_id
        LEFT JOIN intake_details i ON i.post_id = p.id
        LEFT JOIN programs pr ON pr.id = i.program_id
    """,
    # Mirrors `onboarding_readiness()` (`src/domain/logic/users/view.py`):
    # onboarded = email verified AND (a verified clinician — Claim A — OR
    # a verified, non-archived org representation — Claim B). Active =
    # onboarded and has posted or reached out. Excludes admins and
    # deactivated users. Pinned against the Python function by
    # `src/domain/logic/admin_data/test_views.py`.
    "member_onboarding": """
        SELECT
            u.id AS user_id,
            u.created_at AS signed_up_at,
            CASE
                WHEN NOT u.is_verified THEN 'verify_email'
                WHEN NOT (
                    EXISTS (SELECT 1 FROM clinicians c WHERE c.owner_id = u.id AND c.clinician_verified)
                    OR EXISTS (
                        SELECT 1 FROM org_representations r
                        WHERE r.user_id = u.id
                            AND r.authority_status = 'verified'
                            AND r.archived_at IS NULL
                    )
                ) THEN 'verify_identity'
            END AS next_step,
            CASE
                WHEN NOT u.is_verified THEN 'not_onboarded'
                WHEN NOT (
                    EXISTS (SELECT 1 FROM clinicians c WHERE c.owner_id = u.id AND c.clinician_verified)
                    OR EXISTS (
                        SELECT 1 FROM org_representations r
                        WHERE r.user_id = u.id
                            AND r.authority_status = 'verified'
                            AND r.archived_at IS NULL
                    )
                ) THEN 'not_onboarded'
                WHEN EXISTS (SELECT 1 FROM posts p WHERE p.owner_id = u.id)
                    OR EXISTS (SELECT 1 FROM post_connections pc WHERE pc.user_id = u.id)
                    THEN 'active'
                ELSE 'onboarded_inactive'
            END AS status
        FROM users u
        WHERE u.is_active AND NOT u.is_superuser
    """,
    # The latest verdict note per connection (good / not_good).
    "connection_verdicts": """
        SELECT connection_id, verdict
        FROM (
            SELECT
                n.subject_id AS connection_id,
                n.value AS verdict,
                row_number() OVER (
                    PARTITION BY n.subject_id ORDER BY n.created_at DESC, n.rowid DESC
                ) AS rn
            FROM admin_notes n
            WHERE n.subject_type = 'connection' AND n.action = 'verdict'
        )
        WHERE rn = 1
    """,
    # The launch goal's one definition of "good" (Observability spec,
    # "Shared definition: post outcomes"). `week_posted` is the Monday
    # (UTC) of the week the post went up.
    "post_outcomes": """
        WITH early AS (
            SELECT pc.post_id, v.verdict
            FROM post_connections pc
            JOIN posts p ON p.id = pc.post_id
            LEFT JOIN connection_verdicts v ON v.connection_id = pc.id
            WHERE julianday(pc.created_at) - julianday(p.created_at) <= 3
        )
        SELECT
            p.id AS post_id,
            p.created_at AS posted_at,
            date(p.created_at, '-6 days', 'weekday 1') AS week_posted,
            CASE
                WHEN EXISTS (
                    SELECT 1 FROM early e WHERE e.post_id = p.id AND e.verdict = 'good'
                ) THEN 'good'
                WHEN EXISTS (SELECT 1 FROM early e WHERE e.post_id = p.id)
                    AND NOT EXISTS (
                        SELECT 1 FROM early e
                        WHERE e.post_id = p.id
                            AND (e.verdict IS NULL OR e.verdict <> 'not_good')
                    ) THEN 'not_fit'
                WHEN julianday('now') - julianday(p.created_at) >= 3
                    AND NOT EXISTS (SELECT 1 FROM early e WHERE e.post_id = p.id)
                    THEN 'none'
                ELSE 'waiting'
            END AS outcome
        FROM posts p
    """,
}


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "admin_notes",
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "action IN ('reviewed', 'check_in_sent', 'check_in_reply', 'verdict')",
            name="ck_admin_notes_action",
        ),
        sa.CheckConstraint(
            "subject_type IN ('connection', 'post', 'member')",
            name="ck_admin_notes_subject_type",
        ),
        sa.CheckConstraint(
            "value IS NULL OR (action = 'check_in_reply' AND value IN ('yes', 'not_yet', 'no')) OR (action = 'verdict' AND value IN ('good', 'not_good'))",
            name="ck_admin_notes_value",
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_notes_subject",
        "admin_notes",
        ["subject_type", "subject_id"],
        unique=False,
    )
    # ### end Alembic commands ###
    for name, sql in _VIEWS.items():
        op.execute(sa.text(f"CREATE VIEW {name} AS {sql}"))


def downgrade() -> None:
    """Downgrade schema."""
    for name in reversed(list(_VIEWS)):
        op.execute(sa.text(f"DROP VIEW IF EXISTS {name}"))
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index("ix_admin_notes_subject", table_name="admin_notes")
    op.drop_table("admin_notes")
    # ### end Alembic commands ###
