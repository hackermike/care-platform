# Care platform — how to create the new repo (recommendation)

Companion to [[platform-concept.md]]. This answers the practical question:
**new repo + separate session, or build it here?**

## Recommendation: new repo, separate session

Build the platform as its **own repository and its own Claude session**, not in
`breakout-billing` and not in this session. Reasons:

- **The two products diverge at the foundation.** The platform is multi-tenant,
  hosted, Postgres, timezone-aware, with client + therapist + admin roles. Very
  little of `breakout-billing` survives that boundary except the domain layer —
  its auth (`AuthConfig` = one shared password), routing, and single-tenant
  `get_or_create_provider()` are the opposite of what the platform needs.
- **The non-goal is explicit:** *Breakout Billing must never require the platform.*
  Co-locating them, or building both in one session, is how single-tenant
  assumptions and platform PHI quietly leak across that line.
- **"Tightly integrated" is a contract, not co-location.** Integration is
  achieved through a versioned shared library and a documented data contract
  (below) — not by sharing a repo, a database, or a session.

## What "tight integration" actually means here

Two mechanisms, both loose coupling (from [[platform-concept.md]]):

1. **`breakout-core`** — a versioned Python package extracted from this repo
   (domain model, `superbill.py`, `cpt.py`, `finances.py`, `importer.py`) that
   *both* products depend on. No shared DB, no network calls.
2. **A JSON export/import contract** — the platform exports a therapist's
   encounters/payments; the local tool imports them (extends `importer.py`).
   Platform → local is the direction that matters (year-end books in one place;
   leave without losing records).

Defer live API sync.

## Suggested sequence

1. **In this repo / a short session:** extract `breakout-core` — separate the
   pure domain logic from the ORM layer (do it properly, per the caveat in the
   concept note), publish as a package, and have `breakout-billing` depend on it.
   This is the one bridge task that belongs near this codebase.
2. **New repo, new session:** scaffold the platform (`breakout-care` /
   `even-keel` — name TBD, run a USPTO + domain check first), depending on
   `breakout-core`. Start from the four "settle before writing code" questions in
   the concept note (customer, claims-vs-cash, employ-vs-list, launch states).

## Not carried over from the handoff

The handoff bundle also included a **default-telehealth-link** feature branch.
Per the owner's 2026-08-02 answers, **telehealth is out of scope** — do not apply
that branch, and telehealth links are being removed from `breakout-billing`.
