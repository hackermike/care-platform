"""The breakout-core boundary.

`docs/INTEGRATION.md` says the platform depends on breakout-core rather than
reimplementing superbills, CPT codes, or money math. These tests prove the
platform's multi-tenant models actually satisfy its Protocols — not by asserting
the attributes exist, but by feeding real model instances to the real library
functions. If the shapes drift, the shared code breaks here rather than in
production.
"""
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from breakout_core import cpt, finances
from breakout_core.superbill import build_superbill_pdf, service_rows

from app.models.appointment import (
    POS_OFFICE,
    STATUS_COMPLETED,
    STATUS_SCHEDULED,
    Appointment,
)
from app.models.client import Client
from app.models.payment import Payment
from app.models.provider import TherapistProfile
from app.models.user import ROLE_THERAPIST
from tests.conftest import make_tenant, make_user


@pytest.fixture
def practice(db):
    """A therapist, a client, and two sessions with payments."""
    tenant = make_tenant(db, slug="demo")
    user = make_user(db, tenant, "dr@example.com", ROLE_THERAPIST)
    therapist = TherapistProfile(
        tenant_id=tenant.id,
        user_id=user.id,
        name="Alex Reed",
        credentials="LCSW",
        npi="1234567890",
        license_number="LC-9911",
        tax_id="12-3456789",
        address="1 Main St, Springfield",
        phone="555-0100",
        email="alex@example.com",
        practice_name="Riverside Counseling",
    )
    db.add(therapist)
    db.flush()

    client = Client(
        tenant_id=tenant.id,
        therapist_id=therapist.id,
        first_name="Sam",
        last_name="Rivera",
        dob=date(1990, 5, 1),
        diagnosis_codes="F41.1",
        insurance_company="Blue Shield",
        insurance_id="BS-4432",
        group_number="G-77",
        state="CA",
    )
    db.add(client)
    db.flush()

    first = Appointment(
        tenant_id=tenant.id,
        client_id=client.id,
        therapist_id=therapist.id,
        starts_at=datetime(2026, 3, 2, 15, 0, tzinfo=UTC),
        status=STATUS_COMPLETED,
        fee_amount=Decimal("150.00"),
        cpt_code="90837",
        modifier_1="95",
        place_of_service=POS_OFFICE,
    )
    second = Appointment(
        tenant_id=tenant.id,
        client_id=client.id,
        therapist_id=therapist.id,
        starts_at=datetime(2026, 3, 9, 15, 0, tzinfo=UTC),
        status=STATUS_COMPLETED,
        fee_amount=Decimal("150.00"),
        cpt_code="90834",
    )
    db.add_all([first, second])
    db.flush()

    db.add_all(
        [
            Payment(
                tenant_id=tenant.id,
                appointment_id=first.id,
                amount_value=Decimal("150.00"),
                servicer_fee_value=Decimal("4.65"),
            ),
            Payment(
                tenant_id=tenant.id,
                appointment_id=second.id,
                amount_value=Decimal("50.00"),
            ),
        ]
    )
    db.commit()
    return {"tenant": tenant, "therapist": therapist, "client": client,
            "appointments": [first, second]}


class TestMoneyMath:
    """breakout_core.finances, run against platform models."""

    def test_collected_totals_every_payment(self, practice):
        assert finances.total_collected(practice["appointments"]) == 200.0

    def test_balance_on_services(self, practice):
        balance = finances.balance_on_services(practice["appointments"])
        assert balance == {"charged": 300.0, "paid": 200.0, "outstanding": 100.0}

    def test_servicer_fees(self, practice):
        assert finances.total_servicer_fees(practice["appointments"]) == 4.65

    def test_written_off_sessions_are_not_charged(self, db, practice):
        appt = practice["appointments"][0]
        appt.written_off = True
        db.commit()
        assert finances.balance_on_services(practice["appointments"])["charged"] == 150.0

    def test_refunds_count_negatively(self, db, practice):
        appt = practice["appointments"][0]
        db.add(
            Payment(
                tenant_id=practice["tenant"].id,
                appointment_id=appt.id,
                amount_value=Decimal("25.00"),
                is_refund=True,
            )
        )
        db.commit()
        db.refresh(appt)
        assert finances.total_collected(practice["appointments"]) == 175.0

    def test_scheduled_sessions_are_not_yet_charged(self, db, practice):
        appt = practice["appointments"][1]
        appt.status = STATUS_SCHEDULED
        db.commit()
        assert finances.balance_on_services(practice["appointments"])["charged"] == 150.0


class TestSuperbill:
    """breakout_core.superbill, run against platform models."""

    def test_service_rows_use_the_shared_cpt_catalog(self, practice):
        rows = service_rows(practice["appointments"], practice["client"])
        assert rows[0]["cpt"] == "90837"
        assert rows[0]["description"] == cpt.description("90837")
        assert rows[0]["modifiers"] == "95"

    def test_session_diagnosis_falls_back_to_the_clients(self, practice):
        rows = service_rows(practice["appointments"], practice["client"])
        assert rows[0]["diagnosis"] == "F41.1"

    def test_a_real_pdf_is_produced(self, practice):
        pdf = build_superbill_pdf(
            practice["therapist"],
            practice["client"],
            practice["appointments"],
            date(2026, 3, 1),
            date(2026, 3, 31),
        )
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 1000


class TestProtocolSurface:
    """The adapter properties in models/money.py and models/appointment.py."""

    def test_money_is_stored_exactly(self, db, practice):
        payment = db.query(Payment).first()
        assert isinstance(payment.amount_value, Decimal)

    def test_money_is_exposed_as_float_for_breakout_core(self, db, practice):
        payment = db.query(Payment).first()
        # breakout-core's Protocols declare float and its math sums them;
        # mixing Decimal into that sum would raise TypeError.
        assert isinstance(payment.amount, float)
        assert isinstance(payment.signed_amount, float)

    def test_exact_storage_survives_a_sum_that_float_would_spoil(self, db, practice):
        """0.1 + 0.2 != 0.3 in binary floating point. Storage must not care."""
        appt = practice["appointments"][0]
        for cents in ("0.10", "0.20"):
            db.add(
                Payment(
                    tenant_id=practice["tenant"].id,
                    appointment_id=appt.id,
                    amount_value=Decimal(cents),
                )
            )
        db.commit()
        total = sum(
            p.amount_value
            for p in db.query(Payment).filter(Payment.appointment_id == appt.id).all()
        )
        assert total == Decimal("150.30")

    def test_appointment_exposes_datetime_for_the_protocol(self, practice):
        appt = practice["appointments"][0]
        assert appt.datetime == appt.starts_at

    def test_modifiers_omit_empty_slots(self, practice):
        assert practice["appointments"][0].modifiers == ["95"]
        assert practice["appointments"][1].modifiers == []

    def test_client_patient_name(self, practice):
        assert practice["client"].patient_name == "Sam Rivera"

    def test_refund_is_a_flag_not_a_negative_amount(self, db, practice):
        refund = Payment(
            tenant_id=practice["tenant"].id,
            appointment_id=practice["appointments"][0].id,
            amount_value=Decimal("25.00"),
            is_refund=True,
        )
        db.add(refund)
        db.commit()
        assert refund.amount == 25.0
        assert refund.signed_amount == -25.0
