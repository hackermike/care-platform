"""The client portal: intake, e-signature, and statements."""
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.appointment import STATUS_COMPLETED, Appointment
from app.models.audit import ACTION_PHI_VIEWED, AuditLog
from app.models.client import Client
from app.models.forms import FormAssignment, FormSubmission, FormTemplate
from app.models.provider import TherapistProfile
from app.models.user import ROLE_CLIENT, ROLE_THERAPIST
from app.services import intake
from tests.conftest import csrf_token_from, login, make_tenant, make_user

INTAKE_SCHEMA = [
    {"key": "goals", "label": "What brings you in?", "type": "textarea", "required": True},
    {"key": "pronouns", "label": "Pronouns", "type": "text"},
    {"key": "referral", "label": "How did you hear about us?", "type": "choice",
     "options": ["Search", "Friend", "Doctor"]},
]


@pytest.fixture
def portal(db):
    """A tenant with a therapist, a client, and that client's portal login."""
    tenant = make_tenant(db, slug="demo", name="Riverside Counseling")
    therapist_user = make_user(db, tenant, "dr@example.com", ROLE_THERAPIST)
    therapist = TherapistProfile(
        tenant_id=tenant.id, user_id=therapist_user.id, name="Alex Reed",
        credentials="LCSW", npi="1234567890", practice_name="Riverside",
    )
    db.add(therapist)
    db.flush()

    client_user = make_user(db, tenant, "sam@example.com", ROLE_CLIENT)
    record = Client(
        tenant_id=tenant.id, therapist_id=therapist.id, user_id=client_user.id,
        first_name="Sam", last_name="Rivera", state="CA",
    )
    db.add(record)
    db.commit()
    return {"tenant": tenant, "therapist": therapist,
            "user": client_user, "client": record}


def make_template(db, tenant, *, name="Intake", schema=None, body=None, sign=False):
    template = FormTemplate(
        tenant_id=tenant.id, name=name,
        schema_json=json.dumps(schema) if schema else None,
        body=body, requires_signature=sign,
    )
    db.add(template)
    db.flush()
    return template


def assign(db, tenant, template, client):
    assignment = FormAssignment(
        tenant_id=tenant.id, template_id=template.id, client_id=client.id
    )
    db.add(assignment)
    db.commit()
    return assignment


class TestPortalAccess:
    def test_a_client_sees_their_own_portal(self, client, portal):
        login(client, portal["user"].email)
        r = client.get("/portal")
        assert r.status_code == 200
        assert "Sam" in r.text

    def test_the_portal_is_white_labeled(self, client, portal):
        """The client sees their network's name, never the platform's."""
        login(client, portal["user"].email)
        r = client.get("/portal")
        assert "Riverside Counseling" in r.text
        assert "Care Platform" not in r.text

    def test_a_therapist_cannot_reach_the_portal(self, client, db, portal):
        login(client, "dr@example.com")
        assert client.get("/portal").status_code == 403

    def test_an_unlinked_client_account_is_handled_gracefully(self, client, db):
        tenant = make_tenant(db, slug="demo")
        user = make_user(db, tenant, "new@example.com", ROLE_CLIENT)
        login(client, user.email)
        r = client.get("/portal")
        assert r.status_code == 200
        assert "not linked to a client record" in r.text

    def test_another_clients_form_is_404(self, client, db, portal):
        """The portal resolves the client from the session, so this assignment
        simply does not exist for them."""
        other = Client(
            tenant_id=portal["tenant"].id, first_name="Other", last_name="Person"
        )
        db.add(other)
        db.flush()
        template = make_template(db, portal["tenant"], schema=INTAKE_SCHEMA)
        stranger = assign(db, portal["tenant"], template, other)

        login(client, portal["user"].email)
        assert client.get(f"/portal/forms/{stranger.id}").status_code == 404


class TestIntakeSubmission:
    def test_a_form_can_be_completed(self, client, db, portal):
        template = make_template(db, portal["tenant"], schema=INTAKE_SCHEMA)
        assignment = assign(db, portal["tenant"], template, portal["client"])

        login(client, portal["user"].email)
        page = client.get(f"/portal/forms/{assignment.id}")
        assert "What brings you in?" in page.text

        r = client.post(
            f"/portal/forms/{assignment.id}",
            data={"goals": "Anxiety at work", "pronouns": "they/them",
                  "referral": "Friend", "csrf_token": csrf_token_from(page.text)},
            follow_redirects=False,
        )
        assert r.status_code == 303

        submission = db.query(FormSubmission).one()
        assert intake.answers_of(submission)["goals"] == "Anxiety at work"
        db.refresh(assignment)
        assert assignment.is_complete

    def test_a_required_field_is_enforced(self, client, db, portal):
        template = make_template(db, portal["tenant"], schema=INTAKE_SCHEMA)
        assignment = assign(db, portal["tenant"], template, portal["client"])
        login(client, portal["user"].email)
        page = client.get(f"/portal/forms/{assignment.id}")
        r = client.post(
            f"/portal/forms/{assignment.id}",
            data={"goals": "", "csrf_token": csrf_token_from(page.text)},
        )
        assert r.status_code == 400
        assert "required" in r.text
        assert db.query(FormSubmission).count() == 0

    def test_an_invalid_choice_is_rejected(self, client, db, portal):
        template = make_template(db, portal["tenant"], schema=INTAKE_SCHEMA)
        assignment = assign(db, portal["tenant"], template, portal["client"])
        login(client, portal["user"].email)
        page = client.get(f"/portal/forms/{assignment.id}")
        r = client.post(
            f"/portal/forms/{assignment.id}",
            data={"goals": "x", "referral": "Billboard",
                  "csrf_token": csrf_token_from(page.text)},
        )
        assert r.status_code == 400

    def test_fields_outside_the_schema_are_dropped(self, client, db, portal):
        """A submission is client input; storing undeclared keys would let anyone
        with the form URL write arbitrary content into the record."""
        template = make_template(db, portal["tenant"], schema=INTAKE_SCHEMA)
        assignment = assign(db, portal["tenant"], template, portal["client"])
        login(client, portal["user"].email)
        page = client.get(f"/portal/forms/{assignment.id}")
        client.post(
            f"/portal/forms/{assignment.id}",
            data={"goals": "x", "is_admin": "true", "injected": "payload",
                  "csrf_token": csrf_token_from(page.text)},
        )
        answers = intake.answers_of(db.query(FormSubmission).one())
        assert "is_admin" not in answers
        assert "injected" not in answers

    def test_a_form_cannot_be_submitted_twice(self, client, db, portal):
        template = make_template(db, portal["tenant"], schema=INTAKE_SCHEMA)
        assignment = assign(db, portal["tenant"], template, portal["client"])
        login(client, portal["user"].email)
        page = client.get(f"/portal/forms/{assignment.id}")
        token = csrf_token_from(page.text)
        client.post(f"/portal/forms/{assignment.id}",
                    data={"goals": "x", "csrf_token": token})
        r = client.post(f"/portal/forms/{assignment.id}",
                        data={"goals": "y", "csrf_token": token})
        assert r.status_code == 400
        assert db.query(FormSubmission).count() == 1


class TestSignature:
    CONSENT = "I consent to treatment under the terms described above."

    def signed_assignment(self, db, portal):
        template = make_template(
            db, portal["tenant"], name="Consent to treatment",
            body=self.CONSENT, sign=True,
        )
        return template, assign(db, portal["tenant"], template, portal["client"])

    def test_signing_records_the_evidence_set(self, client, db, portal):
        _, assignment = self.signed_assignment(db, portal)
        login(client, portal["user"].email)
        page = client.get(f"/portal/forms/{assignment.id}")
        assert self.CONSENT in page.text

        client.post(
            f"/portal/forms/{assignment.id}",
            data={"signature_name": "Sam Rivera",
                  "csrf_token": csrf_token_from(page.text)},
        )
        submission = db.query(FormSubmission).one()
        assert submission.is_signed
        assert submission.signature_name == "Sam Rivera"
        assert submission.signed_at is not None
        assert submission.signature_ip
        assert submission.document_hash

    def test_signing_requires_a_name(self, client, db, portal):
        _, assignment = self.signed_assignment(db, portal)
        login(client, portal["user"].email)
        page = client.get(f"/portal/forms/{assignment.id}")
        r = client.post(
            f"/portal/forms/{assignment.id}",
            data={"signature_name": "   ", "csrf_token": csrf_token_from(page.text)},
        )
        assert r.status_code == 400
        assert db.query(FormSubmission).count() == 0

    def test_the_signature_binds_to_the_exact_document(self, client, db, portal):
        """The point of document_hash: editing the template afterwards must not
        silently change what a past client appears to have agreed to."""
        template, assignment = self.signed_assignment(db, portal)
        login(client, portal["user"].email)
        page = client.get(f"/portal/forms/{assignment.id}")
        client.post(
            f"/portal/forms/{assignment.id}",
            data={"signature_name": "Sam Rivera",
                  "csrf_token": csrf_token_from(page.text)},
        )
        submission = db.query(FormSubmission).one()
        assert intake.signature_is_intact(submission)

        template.body = "I consent to treatment AND to something I never saw."
        db.commit()
        db.refresh(submission)
        assert not intake.signature_is_intact(submission)

    def test_an_unsigned_submission_is_never_reported_intact(self, db, portal):
        template = make_template(db, portal["tenant"], schema=INTAKE_SCHEMA)
        submission = FormSubmission(
            tenant_id=portal["tenant"].id, template_id=template.id,
            client_id=portal["client"].id,
        )
        db.add(submission)
        db.commit()
        assert not intake.signature_is_intact(submission)


class TestStatement:
    def test_a_client_downloads_their_own_statement(self, client, db, portal):
        db.add(
            Appointment(
                tenant_id=portal["tenant"].id, client_id=portal["client"].id,
                therapist_id=portal["therapist"].id,
                starts_at=datetime(2026, 3, 2, 15, 0, tzinfo=UTC),
                status=STATUS_COMPLETED, fee_amount=Decimal("150.00"),
                cpt_code="90837",
            )
        )
        db.commit()
        login(client, portal["user"].email)
        r = client.get("/portal/statement",
                       params={"start": "2026-01-01", "end": "2026-12-31"})
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")

    def test_the_statement_download_is_audited(self, client, db, portal):
        login(client, portal["user"].email)
        client.get("/portal/statement",
                   params={"start": "2026-01-01", "end": "2026-06-30"})
        entry = (
            db.query(AuditLog)
            .filter(AuditLog.resource_type == "superbill",
                    AuditLog.action == ACTION_PHI_VIEWED)
            .one()
        )
        assert "portal" in entry.detail

    def test_a_reversed_range_is_400(self, client, portal):
        login(client, portal["user"].email)
        r = client.get("/portal/statement",
                       params={"start": "2026-12-31", "end": "2026-01-01"})
        assert r.status_code == 400


class TestFingerprint:
    def test_identical_templates_hash_identically(self, db, portal):
        a = make_template(db, portal["tenant"], name="C", body="text", sign=True)
        b = make_template(db, portal["tenant"], name="C", body="text", sign=True)
        assert intake.document_fingerprint(a) == intake.document_fingerprint(b)

    def test_a_changed_question_changes_the_hash(self, db, portal):
        a = make_template(db, portal["tenant"], schema=INTAKE_SCHEMA)
        before = intake.document_fingerprint(a)
        a.schema_json = json.dumps(INTAKE_SCHEMA + [{"key": "extra", "type": "text"}])
        assert intake.document_fingerprint(a) != before

    def test_an_unreadable_schema_is_an_intake_error(self, db, portal):
        template = make_template(db, portal["tenant"])
        template.schema_json = "{not json"
        with pytest.raises(intake.IntakeError):
            intake.parse_schema(template)


class TestTherapistAssignsForms:
    """The other half of the loop: a therapist gives a client paperwork."""

    def _template(self, db, portal):
        return make_template(db, portal["tenant"], name="Intake", schema=INTAKE_SCHEMA)

    def test_a_therapist_assigns_a_form(self, client, db, portal):
        template = self._template(db, portal)
        db.commit()
        login(client, "dr@example.com")
        page = client.get(f"/app/clients/{portal['client'].id}")
        r = client.post(
            f"/app/clients/{portal['client'].id}/forms",
            data={"template_id": str(template.id),
                  "csrf_token": csrf_token_from(page.text)},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert db.query(FormAssignment).count() == 1

    def test_assigning_twice_does_not_duplicate(self, client, db, portal):
        template = self._template(db, portal)
        db.commit()
        login(client, "dr@example.com")
        page = client.get(f"/app/clients/{portal['client'].id}")
        token = csrf_token_from(page.text)
        for _ in range(2):
            client.post(
                f"/app/clients/{portal['client'].id}/forms",
                data={"template_id": str(template.id), "csrf_token": token},
            )
        assert db.query(FormAssignment).count() == 1

    def test_another_tenants_template_cannot_be_assigned(self, client, db, portal):
        elsewhere = make_tenant(db, slug="elsewhere", name="Elsewhere")
        foreign = make_template(db, elsewhere, name="Foreign form")
        db.commit()
        login(client, "dr@example.com")
        page = client.get(f"/app/clients/{portal['client'].id}")
        r = client.post(
            f"/app/clients/{portal['client'].id}/forms",
            data={"template_id": str(foreign.id),
                  "csrf_token": csrf_token_from(page.text)},
        )
        assert r.status_code == 400
        assert db.query(FormAssignment).count() == 0

    def test_the_assigned_form_reaches_the_client(self, client, db, portal):
        template = self._template(db, portal)
        db.commit()
        login(client, "dr@example.com")
        page = client.get(f"/app/clients/{portal['client'].id}")
        client.post(
            f"/app/clients/{portal['client'].id}/forms",
            data={"template_id": str(template.id),
                  "csrf_token": csrf_token_from(page.text)},
        )
        client.cookies.clear()
        login(client, portal["user"].email)
        assert "Intake" in client.get("/portal").text
