"""Security regressions.

Each test here corresponds to a specific way this application could leak or be
abused. They are grouped separately from the feature tests so that a reviewer
can read the security posture in one place, and so deleting one is a visible act.
"""
import pytest

from app.downloads import attachment_headers, safe_filename
from app.models.client import Client
from app.models.provider import TherapistLicense, TherapistProfile
from app.models.user import ROLE_THERAPIST
from app.routers.auth import _safe_next
from tests.conftest import PASSWORD, csrf_token_from, login, make_tenant, make_user


class TestDownloadFilenames:
    """A client's name is user-controlled and ends up in a header."""

    def test_a_quote_cannot_escape_the_filename(self):
        headers = attachment_headers('superbill-rivera" ; evil="1.pdf')
        value = headers["content-disposition"]
        # Exactly two quotes: the ones this code put there.
        assert value.count('"') == 2
        assert "evil=" not in value.split('filename="')[1].split('"')[0].replace(
            "evil-", ""
        )

    def test_separators_are_stripped(self):
        assert "/" not in safe_filename("../../etc/passwd")
        assert "\\" not in safe_filename(r"..\..\windows\system32")

    def test_newlines_cannot_split_the_header(self):
        assert "\n" not in safe_filename("name\nSet-Cookie: a=b")
        assert "\r" not in safe_filename("name\r\nSet-Cookie: a=b")

    def test_an_entirely_unsafe_name_falls_back(self):
        assert safe_filename("///", fallback="statement.pdf") == "statement.pdf"

    def test_a_normal_name_survives_intact(self):
        assert safe_filename("superbill-rivera-2026-01-01.pdf") == (
            "superbill-rivera-2026-01-01.pdf"
        )

    def test_the_real_route_sanitises(self, client, db):
        """End to end: a hostile last name must not reach the header."""
        tenant = make_tenant(db, slug="demo")
        user = make_user(db, tenant, "dr@example.com", ROLE_THERAPIST)
        profile = TherapistProfile(tenant_id=tenant.id, user_id=user.id, name="Alex")
        db.add(profile)
        db.flush()
        db.add(TherapistLicense(tenant_id=tenant.id, therapist_id=profile.id, state="CA"))
        subject = Client(
            tenant_id=tenant.id, therapist_id=profile.id, first_name="Sam",
            last_name='Rivera" ; evil="1', state="CA",
        )
        db.add(subject)
        db.commit()

        login(client, user.email)
        r = client.get(
            f"/app/clients/{subject.id}/superbill",
            params={"start": "2026-01-01", "end": "2026-12-31"},
        )
        assert r.status_code == 200
        assert r.headers["content-disposition"].count('"') == 2


class TestOpenRedirect:
    """`next=` after login is a phishing vector against exactly these users."""

    @pytest.mark.parametrize(
        "hostile",
        [
            "https://evil.example.com/steal",
            "//evil.example.com",
            "/\\evil.example.com",
            "\\\\evil.example.com",
            "/path\nSet-Cookie: a=b",
            "/path\r\nLocation: https://evil.example.com",
            "/path\twith-tab",
            "javascript:alert(1)",
        ],
    )
    def test_hostile_targets_are_rejected(self, hostile):
        assert _safe_next(hostile) is None

    @pytest.mark.parametrize("ok", ["/app", "/app/clients", "/portal"])
    def test_relative_paths_are_allowed(self, ok):
        assert _safe_next(ok) == ok

    def test_the_login_route_ignores_a_hostile_next(self, client, db):
        tenant = make_tenant(db, slug="demo")
        user = make_user(db, tenant, "dr@example.com", ROLE_THERAPIST)
        page = client.get("/login")
        r = client.post(
            "/login",
            data={"email": user.email, "password": PASSWORD,
                  "next": "//evil.example.com",
                  "csrf_token": csrf_token_from(page.text)},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/app"


class TestMalformedInputIsNotAServerError:
    """A 500 on user input is both a bug and an information leak."""

    @pytest.fixture
    def signed_in(self, client, db):
        tenant = make_tenant(db, slug="demo")
        user = make_user(db, tenant, "dr@example.com", ROLE_THERAPIST)
        profile = TherapistProfile(tenant_id=tenant.id, user_id=user.id, name="Alex")
        db.add(profile)
        db.flush()
        subject = Client(
            tenant_id=tenant.id, therapist_id=profile.id,
            first_name="Sam", last_name="Rivera", state="CA",
        )
        db.add(subject)
        db.commit()
        login(client, user.email)
        return subject

    def test_a_non_numeric_template_id_is_400(self, client, signed_in):
        page = client.get(f"/app/clients/{signed_in.id}")
        r = client.post(
            f"/app/clients/{signed_in.id}/forms",
            data={"template_id": "not-a-number",
                  "csrf_token": csrf_token_from(page.text)},
        )
        assert r.status_code == 400

    def test_a_non_numeric_account_id_is_400(self, client, db):
        from app.models.user import ROLE_ADMIN

        tenant = make_tenant(db, slug="demo")
        admin = make_user(db, tenant, "admin@example.com", ROLE_ADMIN)
        login(client, admin.email)
        page = client.get("/admin/therapists")
        r = client.post(
            "/admin/therapists",
            data={"user_id": "abc", "name": "X",
                  "csrf_token": csrf_token_from(page.text)},
        )
        assert r.status_code == 400


class TestRoutesAreGuarded:
    """Structural: a new route must not silently be public.

    This is the control that outlives any individual reviewer — adding an
    unguarded route fails here rather than waiting to be noticed.
    """

    # Routes that are public by design, and why.
    PUBLIC = {
        ("/login", "GET"),      # the sign-in form itself
        ("/login", "POST"),     # credential submission
        ("/logout", "POST"),    # ending a session needs no role
        ("/", "GET"),           # redirects to login or the user's surface
        ("/healthz", "GET"),    # liveness probe; no tenant, no data
    }

    def test_every_route_requires_a_role_or_is_listed_public(self):
        from app.main import app

        unguarded = []
        for route in app.routes:
            path = getattr(route, "path", None)
            if path is None or not hasattr(route, "methods"):
                continue
            if path.startswith(("/openapi", "/docs", "/redoc")):
                continue
            for method in route.methods - {"HEAD", "OPTIONS"}:
                if (path, method) in self.PUBLIC:
                    continue
                dependencies = str(getattr(route, "dependant", ""))
                source = ""
                endpoint = getattr(route, "endpoint", None)
                if endpoint is not None:
                    import inspect

                    try:
                        source = inspect.getsource(endpoint)
                    except OSError:
                        source = ""
                if "require_" not in source and "require_" not in dependencies:
                    unguarded.append(f"{method} {path}")

        assert not unguarded, (
            "these routes have no role dependency and are not declared public: "
            f"{sorted(unguarded)}"
        )
