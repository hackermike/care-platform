# Integration with Breakout Billing

"Tightly integrated" means a **contract**, not a shared repo, database, or
session. Two mechanisms, both loose coupling. Build 1 and 2; defer 3.

The real integration requirement isn't code reuse — it's that **the therapist is
the shared user**. A therapist may keep a private caseload in Breakout Billing
*and* take platform clients, and their books have to combine into one year-end
income picture and one A/R view. Solve that.

## 1. `breakout-core` — a shared domain package

Extract from `breakout-billing` and publish as a versioned Python package both
products depend on:

- domain model — `Client`, `Appointment`, `Payment`, `Provider`
- superbill / statement PDF generation
- the CPT catalog
- the money math (paid / collected / balance)
- the CSV importer (column-alias matching)

No runtime coupling, no network calls, no shared database.

**Caveat (do it right):** in Billing these are SQLAlchemy declarative classes on
one `Base` with single-tenant assumptions. Extraction should **split pure domain
logic from the ORM layer** so the platform can supply its own multi-tenant
persistence — rather than shipping the ORM models and bolting a `tenant_id` on
(fast, but it will hurt).

**`breakout-core` now exists** — extracted from `breakout-billing` as an
ORM-free package that operates on structural `Protocol`s (`PaymentLike`,
`AppointmentLike`, `ClientLike`, `ProviderLike`). Depend on it here rather than
re-implementing superbills, CPT codes, or money math. Until it's published to a
private index, install it from the billing repo:

```
pip install "breakout-core @ git+https://github.com/hackermike/breakout-billing.git#subdirectory=breakout-core"
```

Your (multi-tenant) models just need to expose the attributes the Protocols
describe. Later: give `breakout-core` its own repo or a private package index and
pin a version.

### As built (M2, 2026-08-06)

The dependency is **pinned to a commit**, not a branch — an unpinned git
dependency means an unrelated push to `breakout-billing` silently changes this
build. Bump it deliberately. It becomes a version pin once `breakout-core` is
published to an index.

The platform models satisfying the Protocols are `Client`, `Appointment`,
`Payment`, and `TherapistProfile`. Two places where the shapes deliberately
differ from storage, both adapted by properties rather than by changing the
schema:

| Protocol wants | Platform stores | Why |
|---|---|---|
| `amount: float`, `fee: float \| None` | `Numeric(10, 2)` → `Decimal` | Binary floats can't represent most cent values and the error compounds across sums. Tolerable for one therapist's superbills; not for claims and remittance reconciliation. See `app/models/money.py`. |
| `datetime` | `starts_at` | A column named `datetime` shadows the stdlib module in every model file that imports it. |

`tests/test_breakout_core.py` is the guard: it feeds real model instances to the
real library functions, so a drift in either shape fails there rather than in
production.

**If `breakout-core` moves to `Decimal`,** `app/models/money.py` and the
properties on `Appointment`/`Payment` are the only things that change.

## 2. JSON export/import contract

The therapist-portability path and the honest "own your data" answer.

- The platform **exports** a therapist's encounters + payments; the local tool
  **imports** them.
- Billing's importer already establishes the client column-matching pattern;
  extend it to appointments and payments.
- **Platform → local is the direction that matters** — it lets a therapist leave
  without losing records and do year-end books in one place.

Define the schema (versioned) as part of this work; keep it stable and documented.

## 3. Live API sync — deferred

Turning the local app into an API client adds tokens/refresh, conflict
resolution, and partial-failure handling to software whose main virtue is running
on one laptop needing nothing. Only worth it if therapists genuinely run both
systems against the same clients at once — an assumption to test, not build on.

## Non-goals

- Breakout Billing must **never require** this platform.
- **No shared database** between the two.
- Don't let platform PHI flow into the local tool casually — the local threat
  model assumes one user on one encrypted disk.
