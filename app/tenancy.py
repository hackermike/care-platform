"""Tenant resolution and scoped database access.

`CLAUDE.md` is explicit that a missing tenant scope is a data-leak bug, not a
style nit, and `docs/ARCHITECTURE.md` requires the scoping to live in *one*
place rather than being repeated per route. This module is that place.

Routes never call `db.query(Model)` directly. They take a `TenantScope` and call
`scope.query(Model)`, which is filtered by construction. Anything tenant-owned
that is fetched, created, or counted goes through here, so "did we remember to
scope this query?" stops being a question a reviewer has to ask per route.
"""
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Query, Session

from app import config
from app.database import get_db
from app.models.tenant import Tenant


class TenantResolutionError(Exception):
    """No tenant could be determined for the request."""


class CrossTenantError(Exception):
    """An object from one tenant was used inside another tenant's scope.

    Raised rather than silently ignored: reaching this means a bug that would
    otherwise have leaked or corrupted data across a tenant boundary.
    """


def _model_is_tenant_owned(model) -> bool:
    return hasattr(model, "tenant_id")


def subdomain_for(host: str) -> str | None:
    """Extract a tenant slug from a request host.

    ``acme.example.com`` -> ``acme`` when TENANT_HOST_SUFFIX is ``example.com``.
    Returns None when the host does not sit under the configured suffix.
    """
    host = (host or "").split(":")[0].strip().lower()
    suffix = config.TENANT_HOST_SUFFIX.strip().lower()
    if not host or not suffix:
        return None
    if not host.endswith("." + suffix):
        return None
    label = host[: -(len(suffix) + 1)]
    # Only a single leading label identifies a tenant; deeper nesting is not ours.
    if not label or "." in label:
        return None
    return label


@dataclass(frozen=True)
class TenantScope:
    """A database session bound to exactly one tenant.

    Every accessor filters by `tenant_id`. There is deliberately no escape hatch
    on this object — code that legitimately needs to cross tenants (migrations,
    platform-level admin tooling) uses a plain Session and says so explicitly.
    """

    db: Session
    tenant: Tenant

    @property
    def tenant_id(self) -> int:
        return self.tenant.id

    def query(self, model) -> Query:
        """A query pre-filtered to this tenant.

        Raises for models with no `tenant_id`: if a tenant-owned table is added
        without the column, this surfaces it at the first query rather than
        after the data has mixed.
        """
        if not _model_is_tenant_owned(model):
            raise CrossTenantError(
                f"{model.__name__} has no tenant_id; it cannot be queried through a "
                "TenantScope. Add the column, or use the session directly if the "
                "table is genuinely platform-wide."
            )
        return self.db.query(model).filter(model.tenant_id == self.tenant_id)

    def get(self, model, pk):
        """Fetch by primary key, scoped. Returns None for another tenant's row.

        Returning None rather than raising is deliberate: to this tenant, another
        tenant's record does not exist, and a 404 leaks less than a 403.
        """
        return self.query(model).filter(model.id == pk).one_or_none()

    def add(self, obj):
        """Stage a new tenant-owned object, stamping tenant_id.

        Setting the column here means a route cannot forget it, and a mismatched
        value is an error rather than a silent cross-tenant write.
        """
        existing = getattr(obj, "tenant_id", None)
        if existing is not None and existing != self.tenant_id:
            raise CrossTenantError(
                f"{type(obj).__name__} belongs to tenant {existing}, "
                f"not {self.tenant_id}."
            )
        obj.tenant_id = self.tenant_id
        self.db.add(obj)
        return obj

    def commit(self) -> None:
        self.db.commit()

    def flush(self) -> None:
        self.db.flush()


def resolve_tenant(request: Request, db: Session) -> Tenant:
    """Map a request to its tenant by host subdomain.

    Local development has no subdomains, so DEV_DEFAULT_TENANT_SLUG stands in —
    but only when APP_ENV is dev, so a misconfigured production host fails
    closed instead of quietly serving one tenant's data to everyone.
    """
    slug = subdomain_for(request.headers.get("host", ""))
    if slug is None and config.IS_DEV:
        slug = config.DEV_DEFAULT_TENANT_SLUG
    if not slug:
        raise TenantResolutionError("No tenant could be resolved for this host.")

    tenant = db.query(Tenant).filter(Tenant.slug == slug).one_or_none()
    if tenant is None:
        raise TenantResolutionError(f"Unknown tenant: {slug}")
    if not tenant.is_active:
        raise TenantResolutionError(f"Tenant is not active: {slug}")
    return tenant


def get_tenant(request: Request, db: Session = Depends(get_db)) -> Tenant:
    return resolve_tenant(request, db)


def get_scope(
    tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)
) -> TenantScope:
    return TenantScope(db=db, tenant=tenant)
