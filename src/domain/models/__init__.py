# Side-effect import: AuditLog is framework-owned (`framework/audit/log.py`)
# but the class declaration must run before Alembic reads `metadata` here,
# otherwise `audit_log` won't be registered for autogenerate. Direct
# consumers should import from `src.framework.audit.log`, not from here.
from src.framework.audit.log import AuditLog  # noqa: F401
from src.framework.persistence.base_model import Base, BaseModel, metadata

from .admin_notes.admin_note import AdminNote
from .clinician_affiliations.clinician_affiliation import ClinicianAffiliation
from .clinicians.clinician import Clinician
from .clinicians.clinician_certification import ClinicianCertification
from .clinicians.clinician_education import ClinicianEducation
from .clinicians.clinician_licensure import ClinicianLicensure
from .enums import (
    CLIENT_AGE_GROUPS,
    INSURANCE_CARRIERS,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
)
from .favorites.user_favorite import UserFavorite
from .org_representations.org_representation import OrgRepresentation
from .organizations.organization import Organization
from .post_connections.post_connection import PostConnection
from .posts.intake_detail import IntakeDetail
from .posts.opening_detail import OpeningDetail
from .posts.post import Post
from .posts.post_kinds import (
    POST_KIND_BY_DETAIL_MODEL,
    POST_KIND_NAMES,
    POST_KINDS,
    PostKindSpec,
)
from .posts.referral_detail import ReferralDetail
from .programs.program import Program
from .saved_searches.saved_search import SavedSearch
from .users.user import User
from .verifications.verification import Verification

__all__ = [
    "AdminNote",
    "Base",
    "BaseModel",
    "ClinicianAffiliation",
    "CLIENT_AGE_GROUPS",
    "Clinician",
    "ReferralDetail",
    "INSURANCE_CARRIERS",
    "LOCATION_AVAILABILITY_OPTIONS",
    "OrgRepresentation",
    "Organization",
    "POST_KIND_BY_DETAIL_MODEL",
    "POST_KIND_NAMES",
    "POST_KINDS",
    "Post",
    "PostConnection",
    "PostKindSpec",
    "Program",
    "SavedSearch",
    "IntakeDetail",
    "OpeningDetail",
    "ClinicianCertification",
    "ClinicianEducation",
    "ClinicianLicensure",
    "US_STATES",
    "User",
    "UserFavorite",
    "Verification",
    "metadata",
]
