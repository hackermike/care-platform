"""Role enforcement and CSRF."""
from app.models.audit import ACTION_ACCESS_DENIED, AuditLog
from tests.conftest import csrf_token_from, login


def test_anonymous_browser_is_sent_to_login(client, tenant):
    r = client.get("/app", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")


def test_login_redirect_preserves_the_target(client, tenant):
    r = client.get("/admin", follow_redirects=False)
    assert "next=/admin" in r.headers["location"]


def test_therapist_cannot_reach_the_admin_surface(client, therapist):
    login(client, therapist.email)
    assert client.get("/admin").status_code == 403


def test_therapist_cannot_reach_the_client_portal(client, therapist):
    login(client, therapist.email)
    assert client.get("/portal").status_code == 403


def test_client_cannot_reach_the_practice_surface(client, clinician_client):
    login(client, clinician_client.email)
    assert client.get("/app").status_code == 403


def test_admin_may_reach_the_practice_surface(client, admin):
    """Admins are therapists' supervisors here — the therapist surface is open
    to them, but the client portal is not."""
    login(client, admin.email)
    assert client.get("/app").status_code == 200
    assert client.get("/portal").status_code == 403


def test_denied_access_is_audited(client, db, therapist):
    login(client, therapist.email)
    client.get("/admin")
    denials = db.query(AuditLog).filter(AuditLog.action == ACTION_ACCESS_DENIED).all()
    assert len(denials) == 1
    assert denials[0].resource_id == "/admin"
    assert denials[0].user_id == therapist.id


class TestCSRF:
    def test_post_without_a_token_is_refused(self, client, therapist):
        login(client, therapist.email)
        r = client.post("/logout", data={})
        assert r.status_code == 403

    def test_post_with_a_wrong_token_is_refused(self, client, therapist):
        login(client, therapist.email)
        r = client.post("/logout", data={"csrf_token": "not-the-token"})
        assert r.status_code == 403

    def test_post_without_the_cookie_is_refused(self, client, therapist):
        login(client, therapist.email)
        page = client.get("/app")
        token = csrf_token_from(page.text)
        client.cookies.delete("care_csrf")
        r = client.post("/logout", data={"csrf_token": token})
        assert r.status_code == 403

    def test_token_may_be_sent_as_a_header(self, client, therapist):
        """HTMX echoes the token in X-CSRF-Token rather than a form field."""
        login(client, therapist.email)
        page = client.get("/app")
        r = client.post(
            "/logout",
            headers={"X-CSRF-Token": csrf_token_from(page.text)},
            follow_redirects=False,
        )
        assert r.status_code == 303

    def test_safe_methods_need_no_token(self, client, therapist):
        login(client, therapist.email)
        assert client.get("/app").status_code == 200

    def test_the_cookie_is_signed(self, client, tenant):
        """A raw, unsigned value in the cookie must not validate — that is what
        stops a subdomain attacker from forging both halves of the pair."""
        client.get("/login")
        signed = client.cookies.get("care_csrf")
        from app.security.csrf import _unsign

        raw = _unsign(signed)
        assert raw is not None and raw != signed


def test_session_from_another_tenant_is_not_honoured(client, db, tenant, therapist):
    """A valid cookie must not work against a different tenant's host."""
    from app.models.session import UserSession

    login(client, therapist.email)
    other = db.query(UserSession).one()
    # Re-point the session at a tenant the request will not resolve to.
    from tests.conftest import make_tenant

    elsewhere = make_tenant(db, slug="elsewhere", name="Elsewhere")
    other.tenant_id = elsewhere.id
    db.commit()

    assert client.get("/app", follow_redirects=False).status_code == 303
