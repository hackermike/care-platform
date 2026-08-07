"""The end-to-end therapist flow: caseload, sessions, notes, money, superbills."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.appointment import STATUS_COMPLETED, Appointment
from app.models.audit import ACTION_PHI_MODIFIED, ACTION_PHI_VIEWED, AuditLog
from app.models.client import Client
from app.models.note import KIND_PROGRESS, KIND_PSYCHOTHERAPY, ClinicalNote
from app.models.payment import Payment
from app.models.provider import TherapistLicense, TherapistProfile
from app.models.user import ROLE_ADMIN, ROLE_THERAPIST
from tests.conftest import csrf_token_from, login, make_tenant, make_user


@pytest.fixture
def practice(db):
    """A tenant with a licensed therapist and one client on their caseload."""
    tenant = make_tenant(db, slug="demo")
    user = make_user(db, tenant, "dr@example.com", ROLE_THERAPIST)
    profile = TherapistProfile(
        tenant_id=tenant.id, user_id=user.id, name="Alex Reed", credentials="LCSW",
        npi="1234567890", practice_name="Riverside",
    )
    db.add(profile)
    db.flush()
    db.add(TherapistLicense(tenant_id=tenant.id, therapist_id=profile.id, state="CA"))
    client = Client(
        tenant_id=tenant.id, therapist_id=profile.id,
        first_name="Sam", last_name="Rivera", state="CA", diagnosis_codes="F41.1",
    )
    db.add(client)
    db.commit()
    return {"tenant": tenant, "user": user, "profile": profile, "client": client}


def token(client_http, path="/app/clients"):
    return csrf_token_from(client_http.get(path).text)


def book(client_http, practice, when="2026-03-02T15:00", cpt_code="90837", fee=""):
    return client_http.post(
        f"/app/clients/{practice['client'].id}/appointments",
        data={
            "starts_at": when, "cpt_code": cpt_code, "fee": fee,
            "csrf_token": token(client_http),
        },
        follow_redirects=False,
    )


class TestCaseload:
    def test_therapist_sees_their_clients(self, client, practice):
        login(client, practice["user"].email)
        r = client.get("/app/clients")
        assert r.status_code == 200
        assert "Sam Rivera" in r.text

    def test_therapist_does_not_see_a_colleagues_client(self, client, db, practice):
        other_user = make_user(db, practice["tenant"], "other@example.com", ROLE_THERAPIST)
        other = TherapistProfile(
            tenant_id=practice["tenant"].id, user_id=other_user.id, name="Jo Kim"
        )
        db.add(other)
        db.flush()
        db.add(
            Client(
                tenant_id=practice["tenant"].id, therapist_id=other.id,
                first_name="Private", last_name="Person", state="CA",
            )
        )
        db.commit()

        login(client, practice["user"].email)
        r = client.get("/app/clients")
        assert "Sam Rivera" in r.text
        assert "Private Person" not in r.text

    def test_a_colleagues_chart_is_404_not_403(self, client, db, practice):
        """403 would confirm the record exists, which is itself a disclosure."""
        other_user = make_user(db, practice["tenant"], "other@example.com", ROLE_THERAPIST)
        other = TherapistProfile(
            tenant_id=practice["tenant"].id, user_id=other_user.id, name="Jo Kim"
        )
        db.add(other)
        db.flush()
        hidden = Client(
            tenant_id=practice["tenant"].id, therapist_id=other.id,
            first_name="Private", last_name="Person", state="CA",
        )
        db.add(hidden)
        db.commit()

        login(client, practice["user"].email)
        assert client.get(f"/app/clients/{hidden.id}").status_code == 404

    def test_admin_sees_the_whole_tenant(self, client, db, practice):
        admin = make_user(db, practice["tenant"], "admin@example.com", ROLE_ADMIN)
        login(client, admin.email)
        r = client.get("/app/clients")
        assert r.status_code == 200
        assert "Sam Rivera" in r.text

    def test_another_tenants_client_is_invisible(self, client, db, practice):
        elsewhere = make_tenant(db, slug="elsewhere", name="Elsewhere")
        db.add(
            Client(
                tenant_id=elsewhere.id, first_name="Other", last_name="Tenant",
                state="CA",
            )
        )
        db.commit()
        login(client, practice["user"].email)
        assert "Other Tenant" not in client.get("/app/clients").text


class TestBooking:
    def test_booking_creates_a_session(self, client, db, practice):
        login(client, practice["user"].email)
        r = book(client, practice)
        assert r.status_code == 303
        assert db.query(Appointment).count() == 1

    def test_fee_defaults_to_the_shared_cpt_catalog(self, client, db, practice):
        from breakout_core import cpt

        login(client, practice["user"].email)
        book(client, practice, cpt_code="90834")
        appt = db.query(Appointment).one()
        assert appt.fee_amount == Decimal(str(cpt.default_fee("90834")))

    def test_booking_is_refused_without_a_matching_licence(self, client, db, practice):
        practice["client"].state = "NY"
        db.commit()
        login(client, practice["user"].email)
        r = book(client, practice)
        assert r.status_code == 400
        assert db.query(Appointment).count() == 0

    def test_booking_is_refused_when_the_client_state_is_unknown(
        self, client, db, practice
    ):
        practice["client"].state = None
        db.commit()
        login(client, practice["user"].email)
        assert book(client, practice).status_code == 400


class TestNotes:
    @pytest.fixture
    def appointment(self, client, db, practice):
        login(client, practice["user"].email)
        book(client, practice)
        return db.query(Appointment).one()

    def save(self, client, appointment, body, kind=KIND_PROGRESS, sign=""):
        page = client.get(f"/app/appointments/{appointment.id}")
        return client.post(
            f"/app/appointments/{appointment.id}/notes",
            data={
                "body": body, "kind": kind, "sign": sign,
                "csrf_token": csrf_token_from(page.text),
            },
            follow_redirects=False,
        )

    def test_a_draft_note_can_be_saved_and_edited(self, client, db, appointment):
        self.save(client, appointment, "First draft.")
        self.save(client, appointment, "Revised draft.")
        note = db.query(ClinicalNote).one()
        assert note.body == "Revised draft."
        assert not note.is_signed

    def test_signing_locks_the_note(self, client, db, appointment):
        self.save(client, appointment, "Session went well.", sign="1")
        note = db.query(ClinicalNote).one()
        assert note.is_signed

        r = self.save(client, appointment, "Sneaky rewrite.")
        assert r.status_code == 403
        db.expire_all()
        assert db.query(ClinicalNote).one().body == "Session went well."

    def test_an_addendum_corrects_a_signed_note(self, client, db, appointment):
        self.save(client, appointment, "Original.", sign="1")
        note = db.query(ClinicalNote).one()
        page = client.get(f"/app/appointments/{appointment.id}")
        r = client.post(
            f"/app/notes/{note.id}/addenda",
            data={"body": "Correction.", "csrf_token": csrf_token_from(page.text)},
            follow_redirects=False,
        )
        assert r.status_code == 303
        db.refresh(note)
        assert [a.body for a in note.addenda] == ["Correction."]
        # The original text is untouched — that is the point.
        assert note.body == "Original."

    def test_progress_and_psychotherapy_notes_are_separate(
        self, client, db, appointment
    ):
        self.save(client, appointment, "Progress.", kind=KIND_PROGRESS)
        self.save(client, appointment, "Process.", kind=KIND_PSYCHOTHERAPY)
        kinds = {n.kind: n.body for n in db.query(ClinicalNote).all()}
        assert kinds == {KIND_PROGRESS: "Progress.", KIND_PSYCHOTHERAPY: "Process."}

    def test_an_unknown_note_kind_is_rejected(self, client, appointment):
        assert self.save(client, appointment, "x", kind="invented").status_code == 400


class TestMoneyAndSuperbill:
    @pytest.fixture
    def completed(self, client, db, practice):
        login(client, practice["user"].email)
        book(client, practice)
        appt = db.query(Appointment).one()
        page = client.get(f"/app/appointments/{appt.id}")
        client.post(
            f"/app/appointments/{appt.id}/complete",
            data={"csrf_token": csrf_token_from(page.text)},
        )
        db.refresh(appt)
        return appt

    def pay(self, client, appt, amount, **extra):
        page = client.get(f"/app/appointments/{appt.id}")
        data = {"amount": amount, "csrf_token": csrf_token_from(page.text)}
        data.update(extra)
        return client.post(
            f"/app/appointments/{appt.id}/payments", data=data, follow_redirects=False
        )

    def test_completing_a_session_makes_it_chargeable(self, completed):
        assert completed.status == STATUS_COMPLETED

    def test_a_payment_is_recorded_exactly(self, client, db, completed):
        self.pay(client, completed, "75.50")
        payment = db.query(Payment).one()
        assert payment.amount_value == Decimal("75.50")
        assert not payment.is_refund

    def test_a_negative_amount_is_rejected(self, client, db, completed):
        """Refunds are a flag, not a sign — the two mean different things."""
        r = self.pay(client, completed, "-25")
        assert r.status_code == 400
        assert db.query(Payment).count() == 0

    def test_a_refund_is_flagged_not_negated(self, client, db, completed):
        self.pay(client, completed, "25", is_refund="1")
        payment = db.query(Payment).one()
        assert payment.amount_value == Decimal("25")
        assert payment.is_refund
        assert payment.signed_amount == -25.0

    def test_the_client_page_shows_breakout_core_totals(self, client, db, completed):
        self.pay(client, completed, "100")
        r = client.get(f"/app/clients/{completed.client_id}")
        assert r.status_code == 200
        assert "$150.00" in r.text  # charged, from the CPT catalog default
        assert "$100.00" in r.text  # paid
        assert "$50.00" in r.text   # outstanding

    def test_a_superbill_pdf_is_produced(self, client, completed):
        r = client.get(
            f"/app/clients/{completed.client_id}/superbill",
            params={"start": "2026-01-01", "end": "2026-12-31"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")
        assert "attachment" in r.headers["content-disposition"]

    def test_a_superbill_for_a_colleagues_client_is_404(self, client, db, practice):
        other_user = make_user(db, practice["tenant"], "o@example.com", ROLE_THERAPIST)
        other = TherapistProfile(
            tenant_id=practice["tenant"].id, user_id=other_user.id, name="Jo"
        )
        db.add(other)
        db.flush()
        hidden = Client(
            tenant_id=practice["tenant"].id, therapist_id=other.id,
            first_name="P", last_name="P", state="CA",
        )
        db.add(hidden)
        db.commit()
        login(client, practice["user"].email)
        assert client.get(f"/app/clients/{hidden.id}/superbill").status_code == 404


class TestPhiAuditing:
    """CLAUDE.md lists audit logging of PHI access as non-negotiable."""

    def test_opening_a_chart_is_recorded(self, client, db, practice):
        login(client, practice["user"].email)
        client.get(f"/app/clients/{practice['client'].id}")
        entries = db.query(AuditLog).filter(AuditLog.action == ACTION_PHI_VIEWED).all()
        assert any(
            e.resource_type == "client" and e.resource_id == str(practice["client"].id)
            for e in entries
        )

    def test_listing_the_caseload_is_recorded(self, client, db, practice):
        login(client, practice["user"].email)
        client.get("/app/clients")
        entries = db.query(AuditLog).filter(AuditLog.action == ACTION_PHI_VIEWED).all()
        assert any(e.resource_id == "list" for e in entries)

    def test_writing_a_note_is_recorded(self, client, db, practice):
        login(client, practice["user"].email)
        book(client, practice)
        appt = db.query(Appointment).one()
        page = client.get(f"/app/appointments/{appt.id}")
        client.post(
            f"/app/appointments/{appt.id}/notes",
            data={"body": "x", "kind": KIND_PROGRESS,
                  "csrf_token": csrf_token_from(page.text)},
        )
        entries = db.query(AuditLog).filter(
            AuditLog.action == ACTION_PHI_MODIFIED,
            AuditLog.resource_type == "clinical_note",
        ).all()
        assert entries

    def test_downloading_a_superbill_is_recorded_with_its_range(
        self, client, db, practice
    ):
        login(client, practice["user"].email)
        client.get(
            f"/app/clients/{practice['client'].id}/superbill",
            params={"start": "2026-01-01", "end": "2026-06-30"},
        )
        entry = (
            db.query(AuditLog)
            .filter(AuditLog.resource_type == "superbill")
            .one()
        )
        assert "2026-01-01..2026-06-30" in entry.detail

    def test_the_audit_log_does_not_contain_phi(self, client, db, practice):
        """An audit log is retained longer and read more widely than the records
        it describes; clinical content in it widens exposure."""
        login(client, practice["user"].email)
        book(client, practice)
        appt = db.query(Appointment).one()
        page = client.get(f"/app/appointments/{appt.id}")
        client.post(
            f"/app/appointments/{appt.id}/notes",
            data={"body": "Client disclosed a specific traumatic event.",
                  "kind": KIND_PROGRESS,
                  "csrf_token": csrf_token_from(page.text)},
        )
        details = " ".join(e.detail or "" for e in db.query(AuditLog).all())
        assert "traumatic" not in details
        assert "Rivera" not in details
        assert "F41.1" not in details


def test_a_session_for_another_tenant_is_not_reachable(client, db, practice):
    """Tenant isolation, at the route level rather than the query level."""
    elsewhere = make_tenant(db, slug="elsewhere", name="Elsewhere")
    other_user = make_user(db, elsewhere, "x@example.com", ROLE_THERAPIST)
    other_profile = TherapistProfile(
        tenant_id=elsewhere.id, user_id=other_user.id, name="Other"
    )
    db.add(other_profile)
    db.flush()
    other_client = Client(
        tenant_id=elsewhere.id, therapist_id=other_profile.id,
        first_name="Foreign", last_name="Client", state="CA",
    )
    db.add(other_client)
    db.flush()
    foreign = Appointment(
        tenant_id=elsewhere.id, client_id=other_client.id,
        therapist_id=other_profile.id,
        starts_at=datetime(2026, 3, 2, 15, 0, tzinfo=UTC), status="scheduled",
    )
    db.add(foreign)
    db.commit()

    login(client, practice["user"].email)
    assert client.get(f"/app/appointments/{foreign.id}").status_code == 404
