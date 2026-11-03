"""`POST_ENTITY` — the single whole-supertype URL face for ``/posts``.

`Post` is the codebase's only polymorphic entity: the supertype owns
the cross-kind invariants (``owner_id``, ``created_at``, audit shape)
while three detail tables (``referral_detail``, ``opening_detail``,
``intake_detail``) carry the per-kind fields. One URL family lists
every kind; the create/edit forms dispatch by ``?kind=X`` on the URL
and the framework's discriminated-union adapter handles dispatch on
POST/PATCH bodies. List/search expose a `kind` filter for narrowing
to one kind without leaving ``/posts``.

``/posts`` is the authenticated landing surface (see
``src/main.py:read_root``). The browse list (`posts/list.html`) adds a
binary **intent toggle** — Referrals (``?kind=referral``) vs Openings
(``?kind=clinician_opening``) — as pure presentation over this same
`kind` filter; ``program_intake`` is deliberately absent from the toggle
(intake is browsed via org pages) while the sidebar `kind` checkbox still
offers every kind.

See the `discriminator` / `discriminator_value` docstring in
[`framework/dispatch/entity_spec.py`](../../framework/dispatch/entity_spec.py)
for the full polymorphic-face contract.
"""

from typing import Final

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.post_connections.repository import PostConnectionRepository
from src.domain.logic.posts.repository import get_post_repository
from src.domain.logic.posts.schema import (
    post_audit_snapshot,
    post_create_adapter,
    post_read_adapter,
    post_update_adapter,
)
from src.domain.logic.programs.repository import ProgramRepository
from src.domain.models import POST_KINDS, Post
from src.domain.models.enums import (
    CLIENT_AGE_GROUP_LABELS,
    CLIENT_AGE_GROUPS,
    INSURANCE_CARRIER_LABELS,
    INSURANCE_CARRIERS,
    LANGUAGE_LABELS,
    LANGUAGES,
    REFERRAL_SERVICE_LABELS,
    REFERRAL_SERVICES,
    SESSION_FORMAT_LABELS,
    SESSION_FORMATS,
    US_STATES,
)
from src.framework.audit.core import make_audited_resource
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    RouteSet,
    Templates,
)
from src.framework.dispatch.filters import ChoiceFilter, TextFilter
from src.framework.dispatch.redirects import Redirects

POST_AUDITED_RESOURCE: Final = make_audited_resource(
    "post",
    post_audit_snapshot,
)


POST_ENTITY: Final[EntitySpec] = EntitySpec(
    name="post",
    url_collection="posts",
    id_param="post_id",
    model=Post,
    repo_dep=get_post_repository,
    auth_deps=AUTHENTICATED,
    auth_policy=OWNER_OR_ADMIN,
    audit=POST_AUDITED_RESOURCE,
    create_adapter=post_create_adapter,
    update_adapter=post_update_adapter,
    read_schema=post_read_adapter,
    list_order_by=Post.created_at.desc(),
    routes=RouteSet(
        list=True,
        detail=True,
        create=True,
        update=True,
        delete=True,
        form_new=True,
        form_edit=True,
    ),
    # Whole-supertype face: `kind` filter exposes the full registry of
    # kinds so list/search can narrow to one kind without leaving
    # ``/posts``. Each kind's display label comes from `POST_KINDS[k].noun`
    # — the same SOT the /posts/form picker headings and the H1 / CTA
    # chain read from.
    # Order mirrors the post forms' own grammar — Type, then where
    # (state / city / session format), then what (services), then who
    # (age / languages), then coverage (insurance) — with the broad
    # free-text filters (keyword, posted-by) trailing at the bottom. The
    # old free-text ``geography`` + the ``include_telehealth`` flag were
    # folded into the structured ``state`` / ``city`` / ``session_format``
    # filters; ``level_of_care`` / ``modality`` were dropped when settings /
    # modalities collapsed onto the single ``services`` axis.
    filters=(
        ChoiceFilter(
            name="kind",
            label="Type",
            choices=tuple((k, POST_KINDS[k].noun) for k in POST_KINDS.names),
            multi=True,
        ),
        ChoiceFilter(
            name="state",
            label="State",
            choices=tuple((s, s) for s in US_STATES),
            multi=True,
        ),
        TextFilter(
            name="city", label="City or area", placeholder="City or area contains…"
        ),
        ChoiceFilter(
            name="session_format",
            label="Session format",
            choices=tuple((v, SESSION_FORMAT_LABELS[v]) for v in SESSION_FORMATS),
            multi=True,
        ),
        ChoiceFilter(
            name="services",
            label="Services",
            choices=tuple((v, REFERRAL_SERVICE_LABELS[v]) for v in REFERRAL_SERVICES),
            multi=True,
        ),
        ChoiceFilter(
            name="age_group",
            label="Age groups",
            choices=tuple((v, CLIENT_AGE_GROUP_LABELS[v]) for v in CLIENT_AGE_GROUPS),
            multi=True,
        ),
        ChoiceFilter(
            name="language",
            label="Languages",
            choices=tuple((v, LANGUAGE_LABELS[v]) for v in LANGUAGES),
            multi=True,
        ),
        ChoiceFilter(
            name="insurance",
            label="Insurance",
            choices=tuple((v, INSURANCE_CARRIER_LABELS[v]) for v in INSURANCE_CARRIERS),
            multi=True,
        ),
        # Broad free-text filter trails the structured facets — reached
        # for less often.
        TextFilter(name="q", label="Keyword", placeholder="Search descriptions…"),
        # `?owner=me` scopes the list to posts the viewer owns
        # (``Post.owner_id == self._requesting_user.id``) — the same
        # single-toggle radio clinicians/orgs expose. Rendered last, as a
        # viewer-relative scope below the content facets; the viewer-id
        # resolution happens in ``PostRepository.list_posts`` via the
        # ``_requesting_user`` field ``handle_list`` stamps on the repo.
        # Powers the "My posts" view (`/posts?owner=me`, each row → Edit).
        ChoiceFilter(
            name="owner",
            label="Owner",
            choices=(("me", "Owned by me"),),
            multi=False,
            radio=True,
        ),
    ),
    templates=Templates(
        list="posts/list.html",
        detail="posts/detail.html",
        search="posts/search.html",
        form_new="posts/form_new.html",
        form_edit="posts/form_edit.html",
    ),
    update_redirect=Redirects.to_detail("posts", "post_id"),
    # Per-viewer detail extras: the viewer's `PostConnection` to this post
    # (or None), so the connect panel can show "Connected · {date}".
    detail_extras_path="src.domain.logic.posts.handlers.post_detail_extras",
    detail_extras_repos=(("post_connection_repo", PostConnectionRepository),),
    # Two authority paths on create (see `_assert_post_payload_authz`):
    # the **self** path (own the per-kind FK row + hold the matching
    # claim) or the **org-rep** path (be a verified rep of the org the
    # listing's `clinician_affiliation_id` points at). The org lookup for
    # the rep path needs `organization_repo`; the self path needs the
    # clinician/program repos for the FK-ownership check.
    payload_authz_path="src.domain.logic.posts.handlers._assert_post_payload_authz",
    payload_authz_repos=(
        ("clinician_repo", ClinicianRepository),
        ("program_repo", ProgramRepository),
        ("organization_repo", OrganizationRepository),
    ),
    discriminator=POST_KINDS,
    # Whole-supertype: no `discriminator_value` or `discriminator_values`.
    # List takes any kind; `?kind=` query param picks the create-form
    # template; the discriminated-union adapter dispatches POST/PATCH.
    form_error_render=True,
)
