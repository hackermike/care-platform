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


class TestSecurityHeaders:
    """Set on every response, because the page that forgets one is the problem."""

    def test_headers_are_present_on_a_page(self, client, db):
        make_tenant(db, slug="demo")
        r = client.get("/login")
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert "content-security-policy" in r.headers

    def test_headers_are_present_on_an_error_response(self, client):
        """No tenant exists, so this 404s from an exception handler — the
        middleware must still have wrapped it."""
        r = client.get("/login")
        assert r.status_code == 404
        assert r.headers["x-frame-options"] == "DENY"

    def test_the_csp_forbids_framing_and_object_embedding(self, client, db):
        make_tenant(db, slug="demo")
        csp = client.get("/login").headers["content-security-policy"]
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp
        assert "form-action 'self'" in csp

    def test_connect_src_allows_no_third_party(self, client, db):
        """A page rendering PHI must not be able to send it anywhere else."""
        make_tenant(db, slug="demo")
        csp = client.get("/login").headers["content-security-policy"]
        assert "connect-src 'self'" in csp

    def test_hsts_is_not_sent_in_dev(self, client, db):
        """Pinning a browser to HTTPS for a host that serves plain HTTP locally
        would break development for as long as the max-age lasts."""
        make_tenant(db, slug="demo")
        assert "strict-transport-security" not in client.get("/login").headers

    def test_hsts_is_sent_outside_dev(self, monkeypatch):
        from app.security import headers

        monkeypatch.setattr(headers.config, "IS_DEV", False)
        assert "strict-transport-security" in headers.security_headers()

    def test_the_target_policy_is_stricter_than_the_current_one(self):
        """The current policy names CDN hosts as a concession; the target does
        not. If these ever converge, the concession has been removed."""
        from app.security.headers import CURRENT_CSP, TARGET_CSP

        assert "cdn.tailwindcss.com" in CURRENT_CSP
        assert "cdn.tailwindcss.com" not in TARGET_CSP
        # Assert the directives directly. Checking only the text before
        # "style-src" would still pass for `style-src 'self' 'unsafe-inline'`.
        assert "script-src 'self';" in TARGET_CSP
        assert "style-src 'self';" in TARGET_CSP
        assert "'unsafe-inline'" not in TARGET_CSP


class TestHeadersOnUnhandledErrors:
    """The gap CodeRabbit found: SecurityHeadersMiddleware cannot see a 500 that
    Starlette's ServerErrorMiddleware builds, because that sits outside every
    user middleware. Verified failing before the Exception handler was added."""

    def _app_with_a_failing_route(self):
        from fastapi.testclient import TestClient

        from app.main import app

        @app.get("/_test_boom")
        async def _boom():  # pragma: no cover - exists to raise
            raise RuntimeError("unhandled")

        return TestClient(app, raise_server_exceptions=False)

    def test_an_unhandled_exception_still_carries_the_headers(self, db):
        client = self._app_with_a_failing_route()
        r = client.get("/_test_boom")
        assert r.status_code == 500
        assert r.headers["x-frame-options"] == "DENY"
        assert "content-security-policy" in r.headers
        assert r.headers["referrer-policy"] == "no-referrer"

    def test_the_error_body_reveals_nothing(self, db):
        """An exception message can carry a query, a record id, or a fragment of
        PHI. None of it belongs in a response."""
        client = self._app_with_a_failing_route()
        r = client.get("/_test_boom")
        assert r.text == "Internal error."
        assert "RuntimeError" not in r.text
        assert "unhandled" not in r.text
