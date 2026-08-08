from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import false, true

from app.database import Base

# What a form is for. Consent documents are signed and become part of the record;
# intake questionnaires collect clinical information.
KIND_INTAKE = "intake"
KIND_CONSENT = "consent"
FORM_KINDS = (KIND_INTAKE, KIND_CONSENT)

FIELD_TEXT = "text"
FIELD_TEXTAREA = "textarea"
FIELD_DATE = "date"
FIELD_CHOICE = "choice"
FIELD_CHECKBOX = "checkbox"
FIELD_TYPES = (FIELD_TEXT, FIELD_TEXTAREA, FIELD_DATE, FIELD_CHOICE, FIELD_CHECKBOX)


class FormTemplate(Base):
    """A form a network asks its clients to complete.

    Tenant-owned, because each network has its own intake questions and its own
    consent language — there is no platform-wide form (docs/DECISIONS.md: the
    portal is white-labeled).

    `body` holds consent text; `schema_json` holds the question list. A template
    may have either or both: a consent document is body-only, an intake
    questionnaire is schema-only, and a consent-with-questions has both.
    """

    __tablename__ = "form_templates"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)

    name = Column(String, nullable=False)
    kind = Column(String, nullable=False, default=KIND_INTAKE)
    body = Column(Text, nullable=True)
    schema_json = Column(Text, nullable=True)

    requires_signature = Column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    is_active = Column(Boolean, nullable=False, default=True, server_default=true())

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    submissions = relationship("FormSubmission", back_populates="template")


class FormAssignment(Base):
    """A form given to a particular client.

    Assignment is explicit rather than "every active template applies to
    everyone", because which paperwork a client owes is a clinical and
    administrative decision, and a client should not be shown consent documents
    that do not apply to them.
    """

    __tablename__ = "form_assignments"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    template_id = Column(
        Integer, ForeignKey("form_templates.id"), nullable=False, index=True
    )
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    template = relationship("FormTemplate")
    client = relationship("Client")

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None


class FormSubmission(Base):
    """What a client actually submitted, and — if signed — what they signed.

    **`document_hash` is the point of this table.** It records a SHA-256 of the
    exact text and questions presented at signing time. Without it, editing a
    consent template later would silently change what every past client appears
    to have agreed to. With it, the record shows precisely what was on screen.

    The signature itself is a typed name plus timestamp, IP, and user agent —
    the ESIGN-style evidence set. It is intentionally not an image: a drawn
    squiggle proves less than a timestamped, hash-bound attestation.
    """

    __tablename__ = "form_submissions"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    template_id = Column(
        Integer, ForeignKey("form_templates.id"), nullable=False, index=True
    )
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    assignment_id = Column(
        Integer, ForeignKey("form_assignments.id"), nullable=True, index=True
    )
    submitted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    answers_json = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())

    # Signature evidence.
    signed_at = Column(DateTime(timezone=True), nullable=True)
    signature_name = Column(String, nullable=True)
    document_hash = Column(String, nullable=True)
    signature_ip = Column(String, nullable=True)
    signature_user_agent = Column(String, nullable=True)

    template = relationship("FormTemplate", back_populates="submissions")
    client = relationship("Client")

    @property
    def is_signed(self) -> bool:
        return self.signed_at is not None
