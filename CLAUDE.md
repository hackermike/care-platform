# CLAUDE.md

Guidance for Claude Code working in this repository.

> **Read `START-HERE.md` first.** Several product decisions are deliberately
> unmade; that file lists them and the recommended first tasks. Don't build past
> a decision that hasn't been made — surface it instead.

## Git commits

- Never add `Co-Authored-By`, AI attribution, or any mention of Claude in commit
  messages or PR bodies.
- Write commit messages in plain past tense from the project's perspective
  (e.g. "Add tenant model", "Fix invite expiry").

## Project overview

**The care platform** — a hosted, multi-tenant companion to
[Breakout Billing](https://github.com/hackermike/breakout-billing) (the solo,
local therapist tool). Where Breakout Billing is one therapist on a laptop, this
is a **network of therapists and their clients**, running hosted under a BAA,
with client-facing scheduling/intake and (depending on the decisions in
`docs/DECISIONS.md`) insurance claims or sliding-scale payments.

The two products integrate by **contract, not co-location**: a shared
`breakout-core` package and a documented JSON export/import spec. See
`docs/INTEGRATION.md`. **Breakout Billing must never require this platform.**

Full concept and prior-art analysis: `docs/CONCEPT.md`. Why this is a separate
repo/session: `docs/NEW-REPO-PLAN.md`.

## Tech stack

**Backend:** Python + FastAPI
**Frontend:** HTMX + Jinja2 + Tailwind (CDN to start; precompile before launch)
**Database:** **PostgreSQL** via SQLAlchemy (multi-tenant — every tenant-scoped
row carries a `tenant_id`). Alembic owns the schema.
**Auth:** real multi-user with roles (client / therapist / admin) — *to build*.

This mirrors the boring, server-rendered approach that worked well in Breakout
Billing, extended for multi-tenancy. Revisit the frontend choice only if a
polished client portal or in-product video becomes central (see DECISIONS).

## Commands

```bash
./start.sh                                   # first run: venv, deps, migrate, serve
docker compose up -d db                      # local Postgres for development
.venv/bin/uvicorn app.main:app --reload      # dev server after first run
.venv/bin/alembic upgrade head               # apply migrations
./dev-scripts/make-migration.sh "msg"        # autogenerate a migration (review it)
./dev-scripts/lint-and-test.sh               # ruff + pytest (local CI equivalent)
./dev-scripts/open-pr.sh "Title" body.md     # open a PR with the body from a file
./dev-scripts/merge-pr.sh 12                 # squash-merge a PR (CI must be green)
.venv/bin/pytest -q                          # tests (SQLite, no external services)
.venv/bin/ruff check .                       # lint
```

**Never use `source .venv/bin/activate`.** Call the venv binaries directly
(`.venv/bin/<tool>`) — `source` can't be allowlisted and prompts on every chained
command.

**Complex shell belongs in a file, not the command line.** Loops, `$(...)`,
conditionals, heredocs, `${VAR}` expansions, and multi-line quoted strings all
trip permission checks that can't be allowlisted. Put reusable workflow in
`dev-scripts/` (committed) and one-off probes in `scripts/dev/` (gitignored);
both are meant to be run by path.

**Never pass a multi-line markdown body as a shell argument** (a newline + `#`
trips path validation). Write PR/commit bodies to a file and use
`gh pr create --body-file <path>` / `git commit -F <path>`.

## Schema changes (Alembic owns the schema)

`app/db_init.run_migrations()` runs `alembic upgrade head` on startup. To change
the schema: edit the model → `./dev-scripts/make-migration.sh "desc"` → **review
the migration** (prefer nullable columns) → it applies on next start.

**Multi-tenancy rule:** every tenant-owned table has a non-null `tenant_id`
foreign key, and every query is tenant-scoped. Don't add a tenant-owned table
without it. A missing scope is a data-leak bug, not a style nit.

## Feature workflow

Ship each feature as its own reviewed PR off `main`:

1. Branch off up-to-date `main`.
2. Implement + add/extend tests.
3. `./dev-scripts/lint-and-test.sh` until green.
4. Commit with `git commit -F <file>` (message in `scripts/dev/`), then
   `./dev-scripts/open-pr.sh "Title" scripts/dev/pr-body.md`.
5. When CI (`.github/workflows/ci.yml`) is green, `./dev-scripts/merge-pr.sh <n>`;
   keep docs in sync.

Prefer these committed scripts over inline `gh`/`git` pipelines — they're
allowlisted in `.claude/settings.json`, so they run without permission prompts.

## Security & PHI

This is **hosted, multi-tenant, and holds PHI** — a different threat model from
the local tool. Non-negotiables as features land: tenant isolation on every
query, real per-user auth + roles, CSRF on state-changing requests, TLS in front,
audit logging of PHI access, and a BAA-covered host + email/SMS provider. Track
these explicitly; don't defer silently.
