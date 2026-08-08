"""The administrator surface: roster, licensure, and accounts.

Admin-only, and every route is tenant-scoped like any other — an admin
administers *their network*, not the platform. Cross-tenant administration would
be a different role with a different threat model, and it does not exist yet.
"""
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse, Response

from app import audit, forms, phi
from app.auth.dependencies import require_admin
from app.models.audit import ACTION_PHI_MODIFIED, AuditLog
from app.models.provider import TherapistLicense, TherapistProfile
from app.models.user import ROLE_THERAPIST, User
from app.services import roster
from app.services.roster import RosterError
from app.templates_config import templates
from app.tenancy import TenantScope, get_scope

router = APIRouter(prefix="/admin")


def _not_found() -> Response:
    return Response("Not found.", status_code=status.HTTP_404_NOT_FOUND)


@router.get("/therapists")
async def therapist_roster(
    request: Request,
    q: str = "",
    page: int = 1,
    user: User = Depends(require_admin),
    scope: TenantScope = Depends(get_scope),
):
    results = roster.therapists(scope, search=q, page=page)
    counts = roster.caseload_sizes(scope, [t.id for t in results.items])
    unassigned = (
        scope.query(User)
        .filter(
            User.role == ROLE_THERAPIST,
            ~User.id.in_(scope.query(TherapistProfile.user_id)),
        )
        .order_by(User.email)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin/therapists.html",
        {
            "request": request, "user": user, "tenant": scope.tenant,
            "results": results, "counts": counts, "q": q,
            "unassigned": unassigned,
            "expiring": roster.expiring_licenses(scope),
        },
    )


@router.post("/therapists")
async def create_therapist(
    request: Request,
    user_id: str = Form(...),
    name: str = Form(...),
    credentials: str = Form(""),
    npi: str = Form(""),
    license_number: str = Form(""),
    practice_name: str = Form(""),
    user: User = Depends(require_admin),
    scope: TenantScope = Depends(get_scope),
):
    account = scope.get(User, forms.parse_int(user_id, "Account"))
    if account is None:
        return _not_found()
    try:
        profile = roster.create_therapist(
            scope,
            account,
            name=forms.required_text(name, "Name", max_length=120),
            credentials=forms.optional_text(credentials, max_length=60),
            npi=forms.optional_text(npi, max_length=20),
            license_number=forms.optional_text(license_number, max_length=60),
            practice_name=forms.optional_text(practice_name, max_length=120),
        )
    except RosterError as exc:
        return Response(str(exc), status_code=status.HTTP_400_BAD_REQUEST)

    scope.flush()
    audit.record(
        scope.db, ACTION_PHI_MODIFIED, tenant_id=scope.tenant_id, user_id=user.id,
        resource_type="therapist_profile", resource_id=profile.id,
        detail="created", request=request,
    )
    scope.commit()
    return RedirectResponse(
        url=f"/admin/therapists/{profile.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/therapists/{therapist_id}")
async def therapist_detail(
    therapist_id: int,
    request: Request,
    user: User = Depends(require_admin),
    scope: TenantScope = Depends(get_scope),
):
    therapist = scope.get(TherapistProfile, therapist_id)
    if therapist is None:
        return _not_found()
    return templates.TemplateResponse(
        request,
        "admin/therapist_detail.html",
        {
            "request": request, "user": user, "tenant": scope.tenant,
            "therapist": therapist,
            "caseload": roster.caseload_sizes(scope, [therapist.id]).get(
                therapist.id, 0
            ),
            "states": sorted(forms.US_STATES),
        },
    )


@router.post("/therapists/{therapist_id}/licenses")
async def add_license(
    therapist_id: int,
    request: Request,
    state: str = Form(...),
    license_number: str = Form(""),
    expires_on: str = Form(""),
    user: User = Depends(require_admin),
    scope: TenantScope = Depends(get_scope),
):
    therapist = scope.get(TherapistProfile, therapist_id)
    if therapist is None:
        return _not_found()

    licence = roster.add_license(
        scope,
        therapist,
        forms.parse_state(state, required=True),
        license_number=forms.optional_text(license_number, max_length=60),
        expires_on=forms.parse_date_as_utc(expires_on, "Expiry date"),
    )
    scope.flush()
    audit.record(
        scope.db, ACTION_PHI_MODIFIED, tenant_id=scope.tenant_id, user_id=user.id,
        resource_type="therapist_license", resource_id=licence.id,
        detail=f"state={licence.state}", request=request,
    )
    scope.commit()
    return RedirectResponse(
        url=f"/admin/therapists/{therapist.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/licenses/{license_id}/remove")
async def remove_license(
    license_id: int,
    request: Request,
    user: User = Depends(require_admin),
    scope: TenantScope = Depends(get_scope),
):
    licence = scope.get(TherapistLicense, license_id)
    if licence is None:
        return _not_found()
    therapist_id = licence.therapist_id
    audit.record(
        scope.db, ACTION_PHI_MODIFIED, tenant_id=scope.tenant_id, user_id=user.id,
        resource_type="therapist_license", resource_id=licence.id,
        detail=f"removed state={licence.state}", request=request,
    )
    roster.remove_license(scope, licence)
    scope.commit()
    return RedirectResponse(
        url=f"/admin/therapists/{therapist_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/audit")
async def audit_trail(
    request: Request,
    page: int = 1,
    action: str = "",
    user: User = Depends(require_admin),
    scope: TenantScope = Depends(get_scope),
):
    """The PHI access log, readable by the people accountable for it.

    An audit log nobody can read is a compliance artefact rather than a control.
    """
    query = scope.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    results = roster.paginate(query.order_by(AuditLog.created_at.desc()), page)

    actors = {
        u.id: u.display_name
        for u in scope.query(User)
        .filter(User.id.in_([e.user_id for e in results.items if e.user_id]))
        .all()
    } if results.items else {}

    phi.viewed(
        scope.db, user, "audit_log", "list", request=request,
        detail=f"page={results.page} action={action or 'all'}",
    )
    scope.commit()
    return templates.TemplateResponse(
        request,
        "admin/audit.html",
        {
            "request": request, "user": user, "tenant": scope.tenant,
            "results": results, "actors": actors, "action": action,
        },
    )
