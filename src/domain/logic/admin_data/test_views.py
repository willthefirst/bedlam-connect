"""Parity pins for observability views that restate app logic in SQL.

`member_onboarding` re-derives onboarding readiness in SQL because the
admin's Datasette can't call Python. If `onboarding_readiness()` changes
(`src/domain/logic/users/view.py`), this test fails until the view —
a new migration — follows.
"""

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from src.domain.logic.users.view import onboarding_readiness
from src.domain.models import OrgRepresentation, User
from tests.helpers import create_test_user, make_clinician, make_organization_row


def _rep(orm: Session, user: User, *, status: str, archived: bool = False) -> None:
    org = make_organization_row(owner_id=user.id, name=f"Org {uuid.uuid4()}")
    orm.add(org)
    orm.add(
        OrgRepresentation(
            user_id=user.id,
            org_id=org.id,
            role="coordinator",
            authority_method="admin_review",
            authority_status=status,
            archived_at=datetime.now(timezone.utc) if archived else None,
        )
    )


@pytest.fixture
def members(orm: Session) -> dict[str, User]:
    cases: dict[str, User] = {}

    def user(name: str, **kwargs) -> User:
        cases[name] = create_test_user(username=name, **kwargs)
        orm.add(cases[name])
        return cases[name]

    user("email_unverified", is_verified=False)
    clinician_but_no_email = user("verified_clinician_no_email", is_verified=False)
    orm.add(make_clinician(owner_id=clinician_but_no_email.id, clinician_verified=True))
    user("no_claim")
    orm.add(make_clinician(owner_id=user("pending_clinician").id))
    orm.add(make_clinician(owner_id=user("claim_a").id, clinician_verified=True))
    _rep(orm, user("claim_b"), status="verified")
    _rep(orm, user("archived_rep"), status="verified", archived=True)
    _rep(orm, user("pending_rep"), status="pending")
    orm.commit()
    return cases


def test_member_onboarding_matches_onboarding_readiness(members, orm, admin_db):
    with sqlite3.connect(admin_db) as conn:
        view = {
            user_id: (status, next_step)
            for user_id, status, next_step in conn.execute(
                "select user_id, status, next_step from member_onboarding"
            )
        }

    for name, user in members.items():
        orm.refresh(user)
        readiness = onboarding_readiness(user)
        status, next_step = view[user.id.hex]
        assert (status != "not_onboarded") == readiness.can_post, name
        assert (next_step == "verify_email") == (not readiness.email_verified), name
        assert (next_step is None) == readiness.can_post, name


def test_member_onboarding_excludes_admins_and_deactivated(orm, admin_db):
    admin = create_test_user(username="admin", is_superuser=True)
    gone = create_test_user(username="gone", is_active=False)
    orm.add_all([admin, gone])
    orm.commit()

    with sqlite3.connect(admin_db) as conn:
        ids = {row[0] for row in conn.execute("select user_id from member_onboarding")}
    assert admin.id.hex not in ids
    assert gone.id.hex not in ids
