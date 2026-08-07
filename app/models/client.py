from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.database import Base


class Client(Base):
    """A person receiving care within one tenant.

    Satisfies `breakout_core.domain.ClientLike`, so superbill generation and
    money math are shared with Breakout Billing rather than reimplemented.

    A client may optionally be linked to a `User` — the portal login. The link is
    nullable because a therapist can have a client record long before that person
    is invited to the portal, and some never will be.
    """

    __tablename__ = "clients"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    therapist_id = Column(
        Integer, ForeignKey("therapist_profiles.id"), nullable=True, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # ClientLike surface.
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    dob = Column(Date, nullable=True)
    diagnosis_codes = Column(String, nullable=True)  # ICD-10, comma-separated
    insurance_company = Column(String, nullable=True)
    insurance_id = Column(String, nullable=True)
    group_number = Column(String, nullable=True)

    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)

    # Where the client is located during sessions. Licensure is per-state and
    # therapists are listed rather than employed (docs/DECISIONS.md), so this is
    # what booking validates against the therapist's licences.
    state = Column(String(2), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    therapist = relationship("TherapistProfile")
    appointments = relationship(
        "Appointment", back_populates="client", cascade="all, delete-orphan"
    )

    @property
    def patient_name(self) -> str:
        """The identified patient's name, for the statement (ClientLike)."""
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def display_name(self) -> str:
        return self.patient_name
