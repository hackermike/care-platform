# Start here

This repo is a **scaffold**, not a built product. It gives a fresh Claude Code
session a running skeleton, the working conventions (`CLAUDE.md`), and the full
concept/plan (`docs/`). Read this file, then `docs/DECISIONS.md`, then start.

## What's already here

- A runnable **FastAPI + Postgres + HTMX** skeleton: health check, a home page,
  a minimal multi-tenant data model (`Tenant`, `User` with a role), Alembic
  wired up, and a green test suite (SQLite-backed, no external services needed).
- The **conventions** that made Breakout Billing pleasant to build (`CLAUDE.md`).
- The **concept + prior art** (`docs/CONCEPT.md`), why this is a separate repo
  (`docs/NEW-REPO-PLAN.md`), the **integration contract** (`docs/INTEGRATION.md`),
  and the **open product decisions** (`docs/DECISIONS.md`).

## Do this first (in order)

1. ~~**Settle the product decisions in `docs/DECISIONS.md`.**~~ **Done
   2026-08-06.** The customer is the therapist network (infrastructure);
   insurance claims are in scope; therapists are listed, not employed; and the
   launch is state-agnostic. In-product video and a substantial client portal are
   also in scope — note that this *reverses* the telehealth default described at
   the bottom of this file. Read `docs/DECISIONS.md` for the full set and
   `docs/MILESTONES.md` for the plan that follows.
2. **Depend on `breakout-core`.** The plan is to extract the shared domain
   (`Client`/`Appointment`/`Payment`/`Provider`, superbill PDF, CPT catalog,
   money math, importer) out of `breakout-billing` into a versioned package this
   platform imports. Until it exists, don't re-implement that domain here — stub
   the boundary and track it. See `docs/INTEGRATION.md`.
3. **Build the multi-tenant foundation** before any feature: real auth with
   client/therapist/admin roles, tenant scoping on every query, and tenant-aware
   sessions. The skeleton's `Tenant`/`User` models are only a starting point.

## Kickoff prompt (paste into the new Claude session)

> Read START-HERE.md, CLAUDE.md, and everything in docs/. This is the hosted,
> multi-tenant care platform that complements Breakout Billing. Before writing
> feature code, walk me through docs/DECISIONS.md and help me settle the four
> product questions — especially "who is the customer" and "claims vs
> sliding-scale" — because they drive the data model and stack. Once we've
> decided, propose a milestone plan: (1) auth + roles + tenant isolation, (2) the
> breakout-core dependency boundary, (3) the first end-to-end therapist flow.
> Ship each as its own reviewed PR off main, following the CLAUDE.md conventions.

## Not carried over

The original handoff included a default-telehealth-link feature branch. Per the
owner's 2026-08-02 decision, **telehealth was dropped from Breakout Billing** —
that still holds, and the branch is not applied here.

**Update 2026-08-06:** the platform *does* host in-product video (milestone M6),
via a BAA-covered vendor. That is a platform decision only; it does not travel
back to Breakout Billing.
