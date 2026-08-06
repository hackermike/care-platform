def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_root_redirects_anonymous_visitors_to_login(client, tenant):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_root_sends_a_signed_in_user_to_their_surface(client, therapist):
    from tests.conftest import login

    login(client, therapist.email)
    r = client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/app"


def test_unknown_tenant_is_a_404(client, db):
    """No tenant exists in this test, so resolution fails — and it must look
    like nothing rather than confirming which networks exist."""
    r = client.get("/login")
    assert r.status_code == 404


def test_inactive_tenant_is_a_404(client, db):
    from tests.conftest import make_tenant

    make_tenant(db, slug="demo", is_active=False)
    assert client.get("/login").status_code == 404


def test_tenant_scoped_user(db):
    from app.models import Tenant, User

    t = Tenant(name="Demo Practice", slug="demo")
    db.add(t)
    db.commit()
    db.add(User(tenant_id=t.id, email="dr@example.com", role="therapist"))
    db.commit()

    user = db.query(User).one()
    assert user.tenant_id == t.id
    assert user.role == "therapist"
