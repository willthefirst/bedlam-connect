"""Per-entity row-count targets.

Sized to keep `dev seed` under ~10s on a fresh DB while populating
every listing page well enough that pagination, filters, and
combinatorial cases (state × insurance × language) all have hits.
"""

from __future__ import annotations

from typing import Final

USER_COUNT: Final[int] = 40
ORGANIZATION_COUNT: Final[int] = 25
ORG_HIERARCHY_HEALTH_SYSTEM_ROOTS: Final[int] = 3
ORG_HIERARCHY_CHILDREN_PER_ROOT: Final[int] = 3
CLINICIAN_COUNT: Final[int] = 150
CLINICIAN_MULTI_AFFILIATION_RATE: Final[float] = 0.25  # ~25% get a 2nd affiliation
PROGRAM_COUNT: Final[int] = 12
REFERRAL_POST_COUNT: Final[int] = 100
OPENING_POST_COUNT: Final[int] = 100
INTAKE_POST_COUNT: Final[int] = 50
VERIFICATION_COUNT: Final[int] = 60
FAVORITE_COUNT: Final[int] = 40
POST_CONNECTION_COUNT: Final[int] = 150
ORG_REPRESENTATION_COUNT: Final[int] = 30
LICENSURES_PER_CLINICIAN_RANGE: Final[tuple[int, int]] = (1, 3)
EDUCATIONS_PER_CLINICIAN_RANGE: Final[tuple[int, int]] = (1, 2)
CERTIFICATIONS_PER_CLINICIAN_RANGE: Final[tuple[int, int]] = (0, 3)
