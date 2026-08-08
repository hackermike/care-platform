# Contributing

Thanks for looking. A few things are worth knowing before you spend time.

## This repository holds design decisions, not just code

Several product questions were settled deliberately and are recorded in
[`docs/DECISIONS.md`](docs/DECISIONS.md) with their reasoning. Please read that
and [`docs/MILESTONES.md`](docs/MILESTONES.md) before proposing changes that cut
across them — a PR that reverses a recorded decision needs to argue with the
reasoning, not just the code.

## Non-negotiables

These are not style preferences; a PR that breaks one will be rejected on
principle:

1. **Every tenant-owned table carries a non-null `tenant_id`, and every query is
   tenant-scoped** via `TenantScope` (`app/tenancy.py`). Never call
   `db.query(...)` directly for tenant-owned data. A missing scope is a data-leak
   bug, not a style nit.
2. **Every route that reads or writes PHI records that it did** (`app/phi.py`) —
   and the audit entry never contains the PHI itself.
3. **State-changing routes are CSRF-protected.** This is app-wide by default;
   don't opt out.
4. **Alembic owns the schema.** Model changes need a migration, and
   `tests/test_migrations.py` will fail if the two disagree.

## Working on it

```bash
docker compose up -d db          # local Postgres
./start.sh                       # venv, deps, migrate, serve
./dev-scripts/lint-and-test.sh   # ruff + pytest — must be green
./dev-scripts/smoke-e2e.sh       # end-to-end against a running server
```

Tests run on SQLite and need no external services. See [`CLAUDE.md`](CLAUDE.md)
for the full set of conventions, including why complex shell belongs in
`dev-scripts/` rather than on the command line.

## Pull requests

- Branch off an up-to-date `main`; one coherent change per PR.
- Add or extend tests. Test names should say what behaviour is protected, not
  just which function is called.
- `./dev-scripts/lint-and-test.sh` green before you open it.
- Write the PR body to a file and use `./dev-scripts/open-pr.sh "Title" body.md`
  — a multi-line markdown body passed as a shell argument trips path validation.
- Explain the *why* in the description, especially for judgement calls. If you
  made a trade-off a reviewer might disagree with, say so rather than hoping it
  goes unnoticed.

Commit messages are plain past tense from the project's perspective ("Add tenant
model", "Fix invite expiry"). Please don't add AI attribution or co-author
trailers.

## Security

Do not report vulnerabilities in a public issue or PR. See
[`SECURITY.md`](SECURITY.md).
