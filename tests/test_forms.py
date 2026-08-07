"""Form parsing. Malformed input must be a 400 with a reason, never a 500."""
from datetime import UTC
from decimal import Decimal

import pytest

from app import forms
from app.forms import FormError


class TestText:
    def test_required_text_strips(self):
        assert forms.required_text("  Sam  ", "First name") == "Sam"

    def test_blank_required_text_is_refused(self):
        with pytest.raises(FormError, match="First name is required"):
            forms.required_text("   ", "First name")

    def test_overlong_text_is_refused(self):
        with pytest.raises(FormError, match="too long"):
            forms.required_text("x" * 300, "Notes", max_length=200)

    def test_optional_text_becomes_none(self):
        assert forms.optional_text("  ") is None


class TestDatetime:
    def test_parses_an_iso_value(self):
        parsed = forms.parse_datetime("2026-03-02T15:00")
        assert parsed.year == 2026 and parsed.hour == 15

    def test_naive_input_is_treated_as_utc(self):
        assert forms.parse_datetime("2026-03-02T15:00").tzinfo == UTC

    def test_an_explicit_offset_is_preserved(self):
        parsed = forms.parse_datetime("2026-03-02T15:00+02:00")
        assert parsed.utcoffset().total_seconds() == 7200

    def test_garbage_is_a_form_error_not_a_crash(self):
        """This is the bug this module exists to prevent: fromisoformat raising
        ValueError straight out of a route handler is a 500."""
        with pytest.raises(FormError, match="not a valid date and time"):
            forms.parse_datetime("not-a-date")

    def test_blank_is_refused(self):
        with pytest.raises(FormError, match="required"):
            forms.parse_datetime("")


class TestMoney:
    def test_parses_to_exact_decimal(self):
        assert forms.parse_money("75.50") == Decimal("75.50")

    def test_tolerates_currency_formatting(self):
        assert forms.parse_money("$1,250.00") == Decimal("1250.00")

    def test_rejects_non_numeric(self):
        with pytest.raises(FormError, match="not a valid amount"):
            forms.parse_money("free")

    def test_rejects_negative(self):
        with pytest.raises(FormError, match="must be positive"):
            forms.parse_money("-25")

    def test_rejects_zero(self):
        with pytest.raises(FormError, match="must be positive"):
            forms.parse_money("0")

    def test_rejects_sub_cent_precision(self):
        with pytest.raises(FormError, match="finer than cents"):
            forms.parse_money("10.005")

    def test_optional_blank_is_none(self):
        assert forms.parse_money("", required=False) is None


class TestState:
    def test_normalises_case(self):
        assert forms.parse_state(" ca ") == "CA"

    def test_accepts_territories(self):
        assert forms.parse_state("PR") == "PR"

    def test_rejects_an_unknown_code(self):
        with pytest.raises(FormError, match="not a valid US state"):
            forms.parse_state("ZZ")

    def test_blank_is_allowed_by_default(self):
        assert forms.parse_state("") is None

    def test_blank_is_refused_when_required(self):
        with pytest.raises(FormError, match="State is required"):
            forms.parse_state("", required=True)


class TestCpt:
    def test_accepts_a_catalog_code(self):
        assert forms.parse_cpt("90834") == "90834"

    def test_blank_falls_back_to_the_catalog_default(self):
        from breakout_core import cpt

        assert forms.parse_cpt("") == cpt.DEFAULT_CODE

    def test_rejects_an_unknown_code(self):
        """Validated against breakout-core so the platform and Breakout Billing
        cannot disagree about which codes exist."""
        with pytest.raises(FormError, match="not a CPT code"):
            forms.parse_cpt("99999")


class TestRoutesReturn400:
    """The whole point: these reach a route and must not be 500s."""

    @pytest.fixture
    def signed_in(self, client, db):
        from app.models.client import Client
        from app.models.provider import TherapistLicense, TherapistProfile
        from app.models.user import ROLE_THERAPIST
        from tests.conftest import login, make_tenant, make_user

        tenant = make_tenant(db, slug="demo")
        user = make_user(db, tenant, "dr@example.com", ROLE_THERAPIST)
        profile = TherapistProfile(tenant_id=tenant.id, user_id=user.id, name="Alex")
        db.add(profile)
        db.flush()
        db.add(TherapistLicense(tenant_id=tenant.id, therapist_id=profile.id, state="CA"))
        subject = Client(
            tenant_id=tenant.id, therapist_id=profile.id,
            first_name="Sam", last_name="Rivera", state="CA",
        )
        db.add(subject)
        db.commit()
        login(client, user.email)
        return subject

    def token(self, client):
        from tests.conftest import csrf_token_from

        return csrf_token_from(client.get("/app/clients").text)

    def test_a_malformed_booking_date_is_400(self, client, signed_in):
        r = client.post(
            f"/app/clients/{signed_in.id}/appointments",
            data={"starts_at": "tomorrow-ish", "csrf_token": self.token(client)},
        )
        assert r.status_code == 400
        assert "not a valid date and time" in r.text

    def test_an_unknown_cpt_code_is_400(self, client, signed_in):
        r = client.post(
            f"/app/clients/{signed_in.id}/appointments",
            data={"starts_at": "2026-03-02T15:00", "cpt_code": "99999",
                  "csrf_token": self.token(client)},
        )
        assert r.status_code == 400

    def test_an_invalid_state_is_400(self, client, signed_in):
        r = client.post(
            "/app/clients",
            data={"first_name": "A", "last_name": "B", "state": "ZZ",
                  "csrf_token": self.token(client)},
        )
        assert r.status_code == 400
        assert "not a valid US state" in r.text

    def test_a_reversed_superbill_range_is_400(self, client, signed_in):
        r = client.get(
            f"/app/clients/{signed_in.id}/superbill",
            params={"start": "2026-12-31", "end": "2026-01-01"},
        )
        assert r.status_code == 400
