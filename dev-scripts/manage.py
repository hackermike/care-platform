#!/usr/bin/env python
"""Administrative CLI: create tenants and users, reset passwords, end sessions.

There is no self-service signup — the platform is sold to networks, and accounts
are provisioned for people, not claimed by them (docs/DECISIONS.md). Until the
M8 admin surface exists, this script is how accounts come into being.

Run with the venv interpreter, from the repo root:

    .venv/bin/python dev-scripts/manage.py create-tenant --name "Demo" --slug demo
    .venv/bin/python dev-scripts/manage.py create-user \\
        --tenant demo --email dr@example.com --role therapist
    .venv/bin/python dev-scripts/manage.py set-password --tenant demo --email dr@example.com
    .venv/bin/python dev-scripts/manage.py list-users --tenant demo
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.auth.sessions import revoke_all_for_user  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import ROLES, User  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402


def _tenant(db, slug: str) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.slug == slug).one_or_none()
    if tenant is None:
        sys.exit(f"No tenant with slug {slug!r}.")
    return tenant


def _user(db, tenant: Tenant, email: str) -> User:
    user = (
        db.query(User)
        .filter(User.tenant_id == tenant.id, User.email == email.strip().lower())
        .one_or_none()
    )
    if user is None:
        sys.exit(f"No user {email!r} in tenant {tenant.slug!r}.")
    return user


def _read_password(provided: str | None) -> str:
    """Prompt when not supplied, so passwords stay out of shell history."""
    if provided:
        return provided
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Confirm: "):
        sys.exit("Passwords did not match.")
    if len(first) < 12:
        sys.exit("Password must be at least 12 characters.")
    return first


def create_tenant(args) -> None:
    db = SessionLocal()
    try:
        if db.query(Tenant).filter(Tenant.slug == args.slug).one_or_none():
            sys.exit(f"Tenant {args.slug!r} already exists.")
        tenant = Tenant(
            name=args.name,
            slug=args.slug,
            brand_name=args.brand_name,
            brand_color=args.brand_color,
            support_email=args.support_email,
        )
        db.add(tenant)
        db.commit()
        print(f"Created tenant {tenant.slug} (id={tenant.id}).")
    finally:
        db.close()


def create_user(args) -> None:
    db = SessionLocal()
    try:
        tenant = _tenant(db, args.tenant)
        email = args.email.strip().lower()
        if (
            db.query(User)
            .filter(User.tenant_id == tenant.id, User.email == email)
            .one_or_none()
        ):
            sys.exit(f"User {email!r} already exists in {tenant.slug!r}.")
        password = _read_password(args.password)
        user = User(
            tenant_id=tenant.id,
            email=email,
            full_name=args.full_name,
            role=args.role,
            password_hash=hash_password(password),
        )
        db.add(user)
        db.commit()
        print(f"Created {user.role} {user.email} in {tenant.slug} (id={user.id}).")
    finally:
        db.close()


def set_password(args) -> None:
    db = SessionLocal()
    try:
        tenant = _tenant(db, args.tenant)
        user = _user(db, tenant, args.email)
        user.password_hash = hash_password(_read_password(args.password))
        user.failed_login_count = 0
        user.locked_until = None
        # A password change ends existing sessions: if the change is a response
        # to a compromise, leaving old sessions live defeats the point.
        revoked = revoke_all_for_user(db, user.id)
        db.commit()
        print(f"Password updated for {user.email}; revoked {revoked} session(s).")
    finally:
        db.close()


def list_users(args) -> None:
    db = SessionLocal()
    try:
        tenant = _tenant(db, args.tenant)
        users = db.query(User).filter(User.tenant_id == tenant.id).order_by(User.id).all()
        if not users:
            print(f"No users in {tenant.slug}.")
            return
        for user in users:
            state = "active" if user.is_active else "disabled"
            print(f"{user.id:>5}  {user.role:<10} {user.email:<40} {state}")
    finally:
        db.close()


def deactivate_user(args) -> None:
    db = SessionLocal()
    try:
        tenant = _tenant(db, args.tenant)
        user = _user(db, tenant, args.email)
        user.is_active = False
        revoked = revoke_all_for_user(db, user.id)
        db.commit()
        print(f"Deactivated {user.email}; revoked {revoked} session(s).")
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-tenant", help="Create a network/practice.")
    p.add_argument("--name", required=True)
    p.add_argument("--slug", required=True, help="Subdomain label, e.g. 'acme'.")
    p.add_argument("--brand-name", default=None, help="Client-facing name, if different.")
    p.add_argument("--brand-color", default=None, help="CSS color, e.g. '#2f6f4e'.")
    p.add_argument("--support-email", default=None)
    p.set_defaults(func=create_tenant)

    p = sub.add_parser("create-user", help="Provision an account.")
    p.add_argument("--tenant", required=True, help="Tenant slug.")
    p.add_argument("--email", required=True)
    p.add_argument("--role", required=True, choices=ROLES)
    p.add_argument("--full-name", default=None)
    p.add_argument("--password", default=None, help="Omit to be prompted (preferred).")
    p.set_defaults(func=create_user)

    p = sub.add_parser("set-password", help="Reset a password and end all sessions.")
    p.add_argument("--tenant", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--password", default=None)
    p.set_defaults(func=set_password)

    p = sub.add_parser("list-users", help="List a tenant's users.")
    p.add_argument("--tenant", required=True)
    p.set_defaults(func=list_users)

    p = sub.add_parser("deactivate-user", help="Disable an account and end its sessions.")
    p.add_argument("--tenant", required=True)
    p.add_argument("--email", required=True)
    p.set_defaults(func=deactivate_user)

    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
