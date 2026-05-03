"""provider_availability intake form fields

Replaces the placeholder specialty/region/accepting_new_clients columns on
`provider_availabilities` with the full intake-form schema (Provider
Information / Location / Availability / Featured Services / Insurance — see
the form spec mirrored in `src/models/post.py` and the form template in
`templates/posts/_provider_availability_fields.html`). Existing rows are
disposable — `dev down --volumes` is the recovery path — so the migration
drops the old columns and adds NOT NULL replacements directly.

Revision ID: b9f4d6e83a21
Revises: a8b3c2f17d49
Create Date: 2026-05-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b9f4d6e83a21"
down_revision: Union[str, None] = "a8b3c2f17d49"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_US_STATES = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
)
_LOCATION_AVAILABILITY = ("yes", "no", "please_contact")
_AGE_GROUPS = (
    "children_0_5",
    "children_6_10",
    "preteens_11_13",
    "adolescents_14_18",
    "young_adults_19_24",
    "adults_25_64",
    "older_adults_65_plus",
)
_LANGUAGE_PREFERRED = ("no", "yes")
_INSURANCE = ("in_network", "out_of_network", "in_and_out_of_network")


def _in_clause(values: tuple[str, ...]) -> str:
    return "'" + "','".join(values) + "'"


def upgrade() -> None:
    """Drop old provider_availabilities columns, add the intake-form columns."""
    with op.batch_alter_table("provider_availabilities") as batch_op:
        batch_op.drop_column("accepting_new_clients")
        batch_op.drop_column("region")
        batch_op.drop_column("specialty")

        # Section 1: Provider Information
        batch_op.add_column(sa.Column("practice_name", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("available_providers", sa.Text(), nullable=False))

        # Section 2: Location
        batch_op.add_column(sa.Column("location_city", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("location_state", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("location_zip", sa.Text(), nullable=False))

        # Section 3: Availability
        batch_op.add_column(sa.Column("in_person_sessions", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("virtual_sessions", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("desired_times", sa.JSON(), nullable=False))

        # Section 4: Featured Services
        batch_op.add_column(sa.Column("services", sa.JSON(), nullable=False))
        batch_op.add_column(sa.Column("treatment_modality", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("settings", sa.JSON(), nullable=False))
        batch_op.add_column(sa.Column("client_focus", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("age_group", sa.Text(), nullable=False))
        batch_op.add_column(
            sa.Column("non_english_services", sa.Text(), nullable=False)
        )

        # Section 5: Insurance
        batch_op.add_column(sa.Column("payment_situation", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("sliding_scale", sa.Boolean(), nullable=False))
        batch_op.add_column(sa.Column("cost", sa.Text(), nullable=True))

        batch_op.create_check_constraint(
            "provider_availabilities_location_state_check",
            f"location_state IN ({_in_clause(_US_STATES)})",
        )
        batch_op.create_check_constraint(
            "provider_availabilities_in_person_sessions_check",
            f"in_person_sessions IN ({_in_clause(_LOCATION_AVAILABILITY)})",
        )
        batch_op.create_check_constraint(
            "provider_availabilities_virtual_sessions_check",
            f"virtual_sessions IN ({_in_clause(_LOCATION_AVAILABILITY)})",
        )
        batch_op.create_check_constraint(
            "provider_availabilities_age_group_check",
            f"age_group IN ({_in_clause(_AGE_GROUPS)})",
        )
        batch_op.create_check_constraint(
            "provider_availabilities_non_english_services_check",
            f"non_english_services IN ({_in_clause(_LANGUAGE_PREFERRED)})",
        )
        batch_op.create_check_constraint(
            "provider_availabilities_payment_situation_check",
            f"payment_situation IN ({_in_clause(_INSURANCE)})",
        )


def downgrade() -> None:
    """Reverse upgrade: drop intake-form columns, restore specialty/region/accepting_new_clients."""
    with op.batch_alter_table("provider_availabilities") as batch_op:
        for constraint in (
            "provider_availabilities_payment_situation_check",
            "provider_availabilities_non_english_services_check",
            "provider_availabilities_age_group_check",
            "provider_availabilities_virtual_sessions_check",
            "provider_availabilities_in_person_sessions_check",
            "provider_availabilities_location_state_check",
        ):
            batch_op.drop_constraint(constraint, type_="check")

        for column in (
            "cost",
            "sliding_scale",
            "payment_situation",
            "non_english_services",
            "age_group",
            "client_focus",
            "settings",
            "treatment_modality",
            "services",
            "desired_times",
            "virtual_sessions",
            "in_person_sessions",
            "location_zip",
            "location_state",
            "location_city",
            "available_providers",
            "practice_name",
        ):
            batch_op.drop_column(column)

        batch_op.add_column(sa.Column("specialty", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("region", sa.Text(), nullable=False))
        batch_op.add_column(
            sa.Column("accepting_new_clients", sa.Boolean(), nullable=False)
        )
