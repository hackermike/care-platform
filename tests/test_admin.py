"""The administrator surface: roster, licensure, and the audit log."""
from datetime import timedelta

import pytest

from app.models.client import Client
from app.models.provider import TherapistLicense, TherapistProfile
from app.models.user import ROLE_ADMIN, ROLE_CLIENT, ROLE_THERAPIST
from app.services import roster
from app.timeutil import utcnow
from tests.conftest import csrf_token_from, login, make_tenant, make_user


@pytest.fixture
def network(db):
    tenant = make_tenant(db, slug="demo", name="Riverside Counseling")
    admin = make_user(db, tenant, "admin@example.com", ROLE_ADMIN)
    return {"tenant": tenant, "admin": admin}


def add_therapist(db, tenant, email, name, **kwargs):
    user = make_user(db, tenant, email, ROLE_THERAPIST)
    profile = TherapistProfile(tenant_id=tenant.id, user_id=user.id, name=name, **kwargs)
    db.add(profile)
    db.commit()
    return profile


class TestRosterAccess:
    def test_a_therapist_cannot_reach_the_roster(self, client, db, network):
        user = make_user(db, network["tenant"], "dr@example.com", ROLE_THERAPIST)
        login(client, user.email)
        assert client.get("/admin/therapists").status_code == 403

    def test_a_client_cannot_reach_the_roster(self, client, db, network):
        user = make_user(db, network["tenant"], "sam@example.com", ROLE_CLIENT)
        login(client, user.email)
        assert client.get("/admin/therapists").status_code == 403

    def test_an_admin_sees_the_roster(self, client, db, network):
        add_therapist(db, network["tenant"], "dr@example.com", "Alex Reed")
        login(client, network["admin"].email)
        r = client.get("/admin/therapists")
        assert r.status_code == 200
        assert "Alex Reed" in r.text

    def test_another_tenants_therapist_is_invisible(self, client, db, network):
        elsewhere = make_tenant(db, slug="elsewhere", name="Elsewhere")
        add_therapist(db, elsewhere, "other@example.com", "Foreign Therapist")
        login(client, network["admin"].email)
        assert "Foreign Therapist" not in client.get("/admin/therapists").text

    def test_another_tenants_therapist_detail_is_404(self, client, db, network):
        elsewhere = make_tenant(db, slug="elsewhere", name="Elsewhere")
        foreign = add_therapist(db, elsewhere, "o@example.com", "Foreign")
        login(client, network["admin"].email)
        assert client.get(f"/admin/therapists/{foreign.id}").status_code == 404


class TestSearchAndPaging:
    def test_search_matches_name(self, client, db, network):
        add_therapist(db, network["tenant"], "a@example.com", "Alex Reed")
        add_therapist(db, network["tenant"], "b@example.com", "Jo Kim")
        login(client, network["admin"].email)
        r = client.get("/admin/therapists", params={"q": "Kim"})
        assert "Jo Kim" in r.text
        assert "Alex Reed" not in r.text

    def test_search_matches_npi(self, client, db, network):
        add_therapist(db, network["tenant"], "a@example.com", "Alex", npi="1234567890")
        add_therapist(db, network["tenant"], "b@example.com", "Jo", npi="9999999999")
        login(client, network["admin"].email)
        r = client.get("/admin/therapists", params={"q": "1234567890"})
        assert "Alex" in r.text and "Jo" not in r.text

    def test_paging_bounds_the_page_size(self, db, network):
        """The scale target is thousands of therapists; the roster must not load
        them all."""
        for i in range(30):
            add_therapist(db, network["tenant"], f"t{i}@example.com", f"T{i:02d}")
        from app.tenancy import TenantScope

        scope = TenantScope(db, network["tenant"])
        page = roster.therapists(scope, page=1)
        assert len(page.items) == roster.PAGE_SIZE
        assert page.total == 30
        assert page.pages == 2
        assert page.has_next and not page.has_previous

    def test_an_out_of_range_page_clamps(self, db, network):
        add_therapist(db, network["tenant"], "a@example.com", "Alex")
        from app.tenancy import TenantScope

        page = roster.therapists(TenantScope(db, network["tenant"]), page=99)
        assert page.page == 1

    def test_caseload_sizes_are_fetched_in_bulk(self, db, network):
        a = add_therapist(db, network["tenant"], "a@example.com", "Alex")
        b = add_therapist(db, network["tenant"], "b@example.com", "Jo")
        for i in range(3):
            db.add(
                Client(
                    tenant_id=network["tenant"].id, therapist_id=a.id,
                    first_name=f"C{i}", last_name="X",
                )
            )
        db.commit()
        from app.tenancy import TenantScope

        counts = roster.caseload_sizes(TenantScope(db, network["tenant"]), [a.id, b.id])
        assert counts == {a.id: 3}


class TestProfileCreation:
    def test_an_admin_gives_an_account_a_clinical_profile(self, client, db, network):
        account = make_user(db, network["tenant"], "dr@example.com", ROLE_THERAPIST)
        login(client, network["admin"].email)
        page = client.get("/admin/therapists")
        r = client.post(
            "/admin/therapists",
            data={"user_id": str(account.id), "name": "Alex Reed",
                  "credentials": "LCSW", "npi": "1234567890",
                  "csrf_token": csrf_token_from(page.text)},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert db.query(TherapistProfile).count() == 1

    def test_a_client_account_cannot_hold_a_clinical_profile(self, client, db, network):
        account = make_user(db, network["tenant"], "sam@example.com", ROLE_CLIENT)
        login(client, network["admin"].email)
        page = client.get("/admin/therapists")
        r = client.post(
            "/admin/therapists",
            data={"user_id": str(account.id), "name": "Sam",
                  "csrf_token": csrf_token_from(page.text)},
        )
        assert r.status_code == 400
        assert db.query(TherapistProfile).count() == 0

    def test_a_second_profile_is_refused(self, client, db, network):
        profile = add_therapist(db, network["tenant"], "dr@example.com", "Alex")
        login(client, network["admin"].email)
        page = client.get("/admin/therapists")
        r = client.post(
            "/admin/therapists",
            data={"user_id": str(profile.user_id), "name": "Alex Again",
                  "csrf_token": csrf_token_from(page.text)},
        )
        assert r.status_code == 400


class TestLicensure:
    def test_adding_a_licence(self, client, db, network):
        therapist = add_therapist(db, network["tenant"], "dr@example.com", "Alex")
        login(client, network["admin"].email)
        page = client.get(f"/admin/therapists/{therapist.id}")
        r = client.post(
            f"/admin/therapists/{therapist.id}/licenses",
            data={"state": "CA", "license_number": "LC-1",
                  "expires_on": "2027-01-31",
                  "csrf_token": csrf_token_from(page.text)},
            follow_redirects=False,
        )
        assert r.status_code == 303
        licence = db.query(TherapistLicense).one()
        assert licence.state == "CA" and licence.license_number == "LC-1"

    def test_readding_a_state_records_a_renewal(self, client, db, network):
        """An admin recording a renewal is doing the same action as recording
        the licence; making them delete first invites deleting the wrong row."""
        therapist = add_therapist(db, network["tenant"], "dr@example.com", "Alex")
        login(client, network["admin"].email)
        page = client.get(f"/admin/therapists/{therapist.id}")
        token = csrf_token_from(page.text)
        client.post(f"/admin/therapists/{therapist.id}/licenses",
                    data={"state": "CA", "expires_on": "2026-01-31",
                          "csrf_token": token})
        client.post(f"/admin/therapists/{therapist.id}/licenses",
                    data={"state": "CA", "expires_on": "2028-01-31",
                          "csrf_token": token})
        licence = db.query(TherapistLicense).one()
        assert licence.expires_on.year == 2028

    def test_an_invalid_state_is_rejected(self, client, db, network):
        therapist = add_therapist(db, network["tenant"], "dr@example.com", "Alex")
        login(client, network["admin"].email)
        page = client.get(f"/admin/therapists/{therapist.id}")
        r = client.post(
            f"/admin/therapists/{therapist.id}/licenses",
            data={"state": "ZZ", "csrf_token": csrf_token_from(page.text)},
        )
        assert r.status_code == 400

    def test_removing_a_licence(self, client, db, network):
        therapist = add_therapist(db, network["tenant"], "dr@example.com", "Alex")
        db.add(
            TherapistLicense(
                tenant_id=network["tenant"].id, therapist_id=therapist.id, state="CA"
            )
        )
        db.commit()
        licence = db.query(TherapistLicense).one()
        login(client, network["admin"].email)
        page = client.get(f"/admin/therapists/{therapist.id}")
        client.post(f"/admin/licenses/{licence.id}/remove",
                    data={"csrf_token": csrf_token_from(page.text)})
        assert db.query(TherapistLicense).count() == 0

    def test_expiring_licences_are_surfaced(self, client, db, network):
        """A lapsed licence means a therapist may be seeing clients they cannot
        lawfully see, and nobody notices unless something checks."""
        therapist = add_therapist(db, network["tenant"], "dr@example.com", "Alex Reed")
        db.add_all([
            TherapistLicense(
                tenant_id=network["tenant"].id, therapist_id=therapist.id,
                state="CA", expires_on=utcnow() - timedelta(days=1),
            ),
            TherapistLicense(
                tenant_id=network["tenant"].id, therapist_id=therapist.id,
                state="NY", expires_on=utcnow() + timedelta(days=365),
            ),
        ])
        db.commit()
        login(client, network["admin"].email)
        r = client.get("/admin/therapists")
        assert "expired or expiring" in r.text

        from app.tenancy import TenantScope

        expiring = roster.expiring_licenses(TenantScope(db, network["tenant"]))
        assert [lic.state for lic in expiring] == ["CA"]


class TestAuditView:
    def test_an_admin_can_read_the_audit_log(self, client, db, network):
        login(client, network["admin"].email)
        r = client.get("/admin/audit")
        assert r.status_code == 200
        assert "auth.login.succeeded" in r.text

    def test_a_therapist_cannot(self, client, db, network):
        user = make_user(db, network["tenant"], "dr@example.com", ROLE_THERAPIST)
        login(client, user.email)
        assert client.get("/admin/audit").status_code == 403

    def test_the_log_can_be_filtered(self, client, db, network):
        login(client, network["admin"].email)
        r = client.get("/admin/audit", params={"action": "auth.login.failed"})
        assert r.status_code == 200
        assert "auth.login.succeeded" not in r.text.split("<tbody>")[1]

    def test_another_tenants_entries_are_not_shown(self, client, db, network):
        elsewhere = make_tenant(db, slug="elsewhere", name="Elsewhere")
        other = make_user(db, elsewhere, "x@example.com", ROLE_ADMIN)
        from app import audit

        audit.record(db, "phi.viewed", tenant_id=elsewhere.id, user_id=other.id,
                     resource_type="client", resource_id="9999")
        db.commit()

        login(client, network["admin"].email)
        r = client.get("/admin/audit")
        assert "9999" not in r.text
