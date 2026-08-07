from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.database import Base

# Note kinds. Progress notes are part of the medical record and are disclosable;
# psychotherapy process notes are the clinician's own and, under HIPAA, are held
# to a stricter standard and excluded from ordinary disclosure.
KIND_PROGRESS = "progress"
KIND_PSYCHOTHERAPY = "psychotherapy"
KINDS = (KIND_PROGRESS, KIND_PSYCHOTHERAPY)


class ClinicalNote(Base):
    """A clinical note attached to one appointment.

    **Signing is what makes a note a record.** An unsigned note is a draft the
    author may still edit; a signed note is locked, because a clinical record
    that can be silently rewritten after the fact is not evidence of anything.
    Corrections after signing are made by addendum, never by editing — that is
    the same rule every real EHR follows, and it is why `signed_at` gates the
    edit path rather than merely decorating the UI.

    Psychotherapy notes are separated from progress notes deliberately: HIPAA
    treats them differently, and mixing them into one field makes it impossible
    to honour that distinction on a records request later.
    """

    __tablename__ = "clinical_notes"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    appointment_id = Column(
        Integer, ForeignKey("appointments.id"), nullable=False, index=True
    )
    author_id = Column(
        Integer, ForeignKey("therapist_profiles.id"), nullable=False, index=True
    )

    kind = Column(String, nullable=False, default=KIND_PROGRESS)
    body = Column(Text, nullable=True)

    signed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)

    appointment = relationship("Appointment", back_populates="notes")
    author = relationship("TherapistProfile")
    addenda = relationship(
        "NoteAddendum", back_populates="note", cascade="all, delete-orphan"
    )

    @property
    def is_signed(self) -> bool:
        return self.signed_at is not None

    @property
    def is_editable(self) -> bool:
        return self.signed_at is None


class NoteAddendum(Base):
    """A correction or addition to an already-signed note.

    Append-only by design: the original note text is never altered, so the record
    shows both what was written at the time and what was corrected later.
    """

    __tablename__ = "note_addenda"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    note_id = Column(Integer, ForeignKey("clinical_notes.id"), nullable=False, index=True)
    author_id = Column(
        Integer, ForeignKey("therapist_profiles.id"), nullable=False, index=True
    )

    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    note = relationship("ClinicalNote", back_populates="addenda")
    author = relationship("TherapistProfile")
