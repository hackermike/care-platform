# Milestone plan

Derived from the decisions settled 2026-08-06 (`DECISIONS.md`). Each milestone
ships as its own reviewed PR off `main`, per the feature workflow in `CLAUDE.md`.

Ordering principle: **the security foundation and the domain boundary come
before any feature**, and the money model is built claims-shaped from the first
migration so the claims milestone attaches rather than rewrites.

## M1 — Auth, roles, tenant isolation ✅

The foundation `START-HERE.md` requires before feature work.

**Shipped.** Key modules: `app/tenancy.py` (the single scoping point),
`app/auth/` (sessions, credentials, role dependencies), `app/security/`
(Argon2id, signed double-submit CSRF, tokens), `app/audit.py`, and
`dev-scripts/manage.py` for provisioning accounts.

- Real per-user auth (password + session), replacing nothing — the skeleton has
  no auth at all.
- `client` / `therapist` / `admin` roles with distinct permissions.
- Sessions carry user, role, and tenant.
- **Tenant scoping enforced in one place** — a session/query dependency, not
  ad hoc per route. A missing scope is a data-leak bug (`CLAUDE.md`).
- CSRF on state-changing requests.
- PHI audit-log table and the write path for it.

Audit logging and CSRF land here rather than later because retrofitting either
across an existing surface is far more expensive than starting with them.

## M2 — The `breakout-core` boundary ✅

- Depend on `breakout-core` (already extracted, ORM-free, structural
  `Protocol`s — see `INTEGRATION.md`).
- Make the platform's multi-tenant models satisfy `ClientLike`,
  `AppointmentLike`, `PaymentLike`, `ProviderLike`.
- Do not re-implement superbills, the CPT catalog, or money math here.

Proves the contract holds against multi-tenant persistence before anything is
built on top of it.

**Shipped.** `Client`, `Appointment`, `Payment`, `TherapistProfile` (all
tenant-scoped) satisfy the Protocols; `tests/test_breakout_core.py` proves it by
running the real library against real model instances, up to generating an
actual superbill PDF.

Two decisions worth knowing about:

- **Money is stored as `Numeric(10, 2)`, not float.** `breakout-core`'s
  Protocols declare `float` — fine for a solo superbill tool, wrong for a
  platform that will submit claims and reconcile remittances. Storage stays
  exact and float appears only at the library boundary, via properties in
  `app/models/money.py`. That file is the only thing that changes if
  `breakout-core` later moves to `Decimal`.
- **Claims-shaping arrived early.** CPT code, modifiers, diagnosis codes, and
  place of service are on `Appointment` now, and `Payment` already has an
  `insurance` method, so M7 attaches a `Claim` to these rows instead of
  restructuring them.

`TherapistLicense` and `app/licensure.py` also land here — the residue of the
state-agnostic decision. An unknown client state fails closed.

## M3 — First end-to-end therapist flow

Client → appointment → session note → charge → payment → superbill.

- Timezone-aware datetimes throughout (Billing's naive-local approach does not
  survive multi-tenant hosting).
- **The money model gets its claims shape here:** `Charge` carrying CPT,
  diagnosis, and place-of-service, with a nullable `Claim` relationship, so M7
  attaches to it instead of rewriting it.
- Clinical notes land in this milestone — they are the therapist's daily surface
  and they feed claim construction.

## M4 — Client portal v1

- Client login (the authz model's first real test with a non-staff user).
- Intake forms, e-signature, billing document download.
- **Per-tenant theming** — the portal is white-labeled (`DECISIONS.md`), so the
  `Tenant` model carries branding from this point.

## M5 — Messaging

HIPAA-compliant therapist ↔ client chat via a BAA-covered vendor. Retention
policy and audit coverage designed in, not added afterward.

## M6 — Video visits

Vendor SDK (BAA-covered) embedded in the session view. Recording and retention
policy decided explicitly rather than inherited from the vendor's default.

Note: this reverses the working default in `START-HERE.md` — telehealth was
dropped from Breakout Billing, and is deliberately **in scope** here.

## M7 — Claims

The largest milestone by a wide margin.

- Payer and plan records; eligibility checks.
- Claim submission and remittance reconciliation **via an API-first billing
  partner** — the platform does not generate 837s or parse 835s itself.
- Denial and resubmission workflow.
- Credentialing tracking: per-therapist × per-payer × per-state.

Credentialing is an operational business as much as a data model. Scope it as
such when the milestone is planned in detail.

## M8 — Admin surface at scale

Multiple admins, thousands of therapists: therapist onboarding, state licensure
records, **client-state vs. therapist-licensure validation at booking** (the
engineering residue of the state-agnostic decision), roster management, and
reporting.

## Not in this plan

- **Live API sync with Breakout Billing** — deferred by `INTEGRATION.md`. The
  JSON export/import contract (platform → local) is the portability path; slot it
  in after M3, when there are encounters and payments worth exporting.
- **Consumer marketplace features** — the customer is the network
  (`DECISIONS.md`).
