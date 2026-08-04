def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_home_page_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Care Platform" in r.text


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
