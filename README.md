# Care Platform (working name)

A hosted, multi-tenant companion to
[Breakout Billing](https://github.com/hackermike/breakout-billing) — the solo,
local therapist tool. This product serves a **network of therapists and their
clients**: client-facing scheduling and intake, in-product sessions, and payments
(insurance claims and/or sliding scale — see `docs/DECISIONS.md`).

> **Status: scaffold.** Runnable skeleton + docs only. No product features yet.
> Start with [`START-HERE.md`](START-HERE.md).

The name is a placeholder — `docs/CONCEPT.md` weighs *Breakout Care* (infra) vs
*Even Keel* (consumer). Run a USPTO + domain check before committing to one.

## The two products and the boundary

| | Breakout Billing | This platform |
|---|---|---|
| User | one therapist | a network of therapists + clients |
| Runs | on a laptop (localhost) | hosted, multi-tenant, under a BAA |
| Money | self-pay / superbills | claims and/or sliding scale |
| Client sees | nothing (no client login) | intake, scheduling, sessions, payments |

They integrate by **contract, not co-location** — a shared `breakout-core`
package + a JSON export/import spec (`docs/INTEGRATION.md`). **Breakout Billing
never depends on this platform.**

## Quick start (development)

```bash
docker compose up -d db     # local Postgres
./start.sh                  # venv, install, migrate, run -> http://localhost:8000
```

Tests need no database (SQLite-backed):

```bash
.venv/bin/pip install -r requirements-dev.txt
./dev-scripts/lint-and-test.sh
```

## Tech stack

FastAPI · HTMX + Jinja2 + Tailwind · PostgreSQL via SQLAlchemy (multi-tenant) ·
Alembic migrations. See `CLAUDE.md` for conventions and `docs/ARCHITECTURE.md`
for the target shape.

## Docs

- [`START-HERE.md`](START-HERE.md) — read first; what's here and what to do next
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — the open product decisions (settle these first)
- [`docs/CONCEPT.md`](docs/CONCEPT.md) — full concept, prior art, naming
- [`docs/NEW-REPO-PLAN.md`](docs/NEW-REPO-PLAN.md) — why separate repo/session
- [`docs/INTEGRATION.md`](docs/INTEGRATION.md) — breakout-core + JSON contract
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — target architecture

## License

**Undecided** — a deliberate call, not an oversight. Breakout Billing is
AGPL-3.0; this platform's license depends on the business model in
`docs/DECISIONS.md` (infrastructure-for-networks vs consumer product). No
`LICENSE` file is committed yet; the repo is private until decided.
