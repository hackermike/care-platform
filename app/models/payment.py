from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.money import Money, to_float

METHOD_CARD = "card"
METHOD_CASH = "cash"
METHOD_CHECK = "check"
METHOD_TRANSFER = "transfer"
# Money arriving from a payer rather than the client. Present from M2 so the
# remittance work in M7 has somewhere to land without a schema change.
METHOD_INSURANCE = "insurance"
METHODS = (METHOD_CARD, METHOD_CASH, METHOD_CHECK, METHOD_TRANSFER, METHOD_INSURANCE)


class Payment(Base):
    """Money received against one appointment.

    Satisfies `breakout_core.domain.PaymentLike`.

    A refund is a row with `is_refund` set, not a negative amount: storing the
    magnitude positively and the direction separately means a query for "what
    did we refund" is a filter rather than a sign test, and an accidental
    negative can be rejected outright.
    """

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    appointment_id = Column(
        Integer, ForeignKey("appointments.id"), nullable=False, index=True
    )

    # Exact storage; float only at the breakout-core boundary (models/money.py).
    amount_value = Column(Money, nullable=False)
    servicer_fee_value = Column(Money, nullable=True)  # card-processor fee
    is_refund = Column(Boolean, nullable=False, default=False, server_default="0")

    method = Column(String, nullable=True)
    reference = Column(String, nullable=True)  # cheque number, processor id
    paid_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    appointment = relationship("Appointment", back_populates="payments")

    # --- breakout_core.domain.PaymentLike ---------------------------------

    @property
    def amount(self) -> float:
        return to_float(self.amount_value) or 0.0

    @property
    def servicer_fee(self) -> float | None:
        return to_float(self.servicer_fee_value)

    @property
    def signed_amount(self) -> float:
        """Amount as it affects totals: negative for a refund (PaymentLike)."""
        return -self.amount if self.is_refund else self.amount
