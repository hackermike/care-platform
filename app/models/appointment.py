from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.money import Money, to_float

# Appointment lifecycle. "completed" is the only chargeable status — see
# breakout_core.finances.CHARGEABLE_STATUS, which this must stay aligned with.
STATUS_SCHEDULED = "scheduled"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"
STATUS_NO_SHOW = "no_show"
STATUSES = (STATUS_SCHEDULED, STATUS_COMPLETED, STATUS_CANCELLED, STATUS_NO_SHOW)

# CMS place-of-service codes. Stored per appointment rather than inferred,
# because a claim is rejected for the wrong one and telehealth vs office is
# exactly the distinction payers care about.
POS_OFFICE = "11"
POS_TELEHEALTH_HOME = "10"
POS_TELEHEALTH_OTHER = "02"


class Appointment(Base):
    """One session.

    Satisfies `breakout_core.domain.AppointmentLike`.

    Claims-shaped from the outset (docs/DECISIONS.md): CPT code, modifiers,
    diagnosis codes, and place of service are all here in M2 even though claim
    submission is M7, so that milestone attaches a `Claim` to these rows rather
    than restructuring them.
    """

    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    therapist_id = Column(
        Integer, ForeignKey("therapist_profiles.id"), nullable=False, index=True
    )

    # Timezone-aware, unlike Breakout Billing's naive local times — a hosted
    # platform serves networks across states (docs/DECISIONS.md).
    starts_at = Column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes = Column(Integer, nullable=True)

    status = Column(String, nullable=False, default=STATUS_SCHEDULED)
    written_off = Column(Boolean, nullable=False, default=False, server_default="0")

    # Exact storage; exposed as float at the breakout-core boundary (models/money.py).
    fee_amount = Column(Money, nullable=True)

    cpt_code = Column(String, nullable=True)
    modifier_1 = Column(String, nullable=True)
    modifier_2 = Column(String, nullable=True)
    diagnosis_codes = Column(String, nullable=True)
    place_of_service = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    client = relationship("Client", back_populates="appointments")
    therapist = relationship("TherapistProfile")
    payments = relationship(
        "Payment", back_populates="appointment", cascade="all, delete-orphan"
    )
    notes = relationship(
        "ClinicalNote", back_populates="appointment", cascade="all, delete-orphan"
    )

    # --- breakout_core.domain.AppointmentLike -----------------------------
    # The protocol names differ from the column names where storage and the
    # shared library disagree (float vs Decimal, and `datetime` shadowing the
    # stdlib module). These properties are the whole adapter.

    @property
    def datetime(self):
        """AppointmentLike.datetime — the column is `starts_at`, because
        `datetime` as a column name shadows the module in any model file."""
        return self.starts_at

    @property
    def fee(self) -> float | None:
        return to_float(self.fee_amount)

    @property
    def modifiers(self) -> list[str]:
        """Non-empty CPT modifiers, in order (AppointmentLike)."""
        return [m for m in (self.modifier_1, self.modifier_2) if m]
