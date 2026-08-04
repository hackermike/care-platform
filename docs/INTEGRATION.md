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

**Until `breakout-core` exists:** stub the boundary in this repo (a thin
`app/domain/` interface) and track the dependency. Don't re-implement superbills,
CPT codes, or money math here.

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
