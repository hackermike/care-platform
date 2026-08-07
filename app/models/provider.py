from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.database import Base


class TherapistProfile(Base):
    """The clinical and billing identity of a therapist.

    Separate from `User`, which is an account. A user is how someone signs in; a
    profile is who they are on a superbill or a claim — NPI, license, tax ID.
    Keeping them apart means an admin can hold an account without a clinical
    identity, and a therapist's billing details can change without touching auth.

    Satisfies `breakout_core.domain.ProviderLike`.
    """

    __tablename__ = "therapist_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_therapist_profiles_user"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # ProviderLike surface.
    name = Column(String, nullable=True)
    credentials = Column(String, nullable=True)  # e.g. "LCSW", "PhD"
    npi = Column(String, nullable=True)
    license_number = Column(String, nullable=True)
    tax_id = Column(String, nullable=True)
    address = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    practice_name = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    licenses = relationship(
        "TherapistLicense", back_populates="therapist", cascade="all, delete-orphan"
    )


class TherapistLicense(Base):
    """A therapist's licence to practise in one state.

    The engineering residue of the state-agnostic launch decision
    (docs/DECISIONS.md): licensure is per-state, therapists are listed rather
    than employed, so the platform records where each therapist may practise and
    checks it when a client books.
    """

    __tablename__ = "therapist_licenses"
    __table_args__ = (
        UniqueConstraint(
            "therapist_id", "state", name="uq_therapist_licenses_therapist_state"
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    therapist_id = Column(
        Integer, ForeignKey("therapist_profiles.id"), nullable=False, index=True
    )

    state = Column(String(2), nullable=False)  # USPS code, e.g. "CA"
    license_number = Column(String, nullable=True)
    expires_on = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    therapist = relationship("TherapistProfile", back_populates="licenses")
