# Deployment — what must be plugged in

**Status: this cannot yet hold real PHI.** The application logic is real and
tested; the operational surface around it is not built. This file is the honest
list of what stands between here and a system that may lawfully see a patient.

Ordered by what blocks what.

**Closed 2026-08-08:** CI now runs the full suite against PostgreSQL as well as
SQLite, and applies the migration chain forwards, back to base, and forwards
again on Postgres (`dev-scripts/check-migrations.sh`). The money and timezone
columns are no longer unverified on the production database.

## 1. Blocking — must exist before any real patient data

| Gap | Why it blocks | Where it goes |
|---|---|---|
| **BAA-covered host** | Holding PHI without a Business Associate Agreement is a HIPAA violation regardless of how good the code is. | AWS / GCP / Azure, signed before first real record. |
| **TLS termination** | Session cookies are `Secure` outside dev, so the app is unusable without HTTPS — and unencrypted PHI in transit is a breach. | Reverse proxy (Caddy, nginx, ALB) in front of uvicorn. |
| **`SECRET_KEY` from a secrets manager** | Signs CSRF tokens. The app refuses to boot without a real value when `APP_ENV != dev`, but it must not come from a `.env` file on the box. | AWS Secrets Manager / GCP Secret Manager, injected as env. |
| **Managed Postgres with encryption at rest + backups** | The app does no encryption of its own; that is delegated to the host. No backup policy exists. | RDS / Cloud SQL, PITR enabled, restores actually tested. |
| **`TENANT_HOST_SUFFIX` set** | Tenants resolve by host subdomain. Unset outside dev, every request fails closed — which is correct, and also means nothing works. | Env var + wildcard DNS + wildcard TLS cert. |

## 2. Blocking for real users — the product is unusable without these

| Gap | Consequence today |
|---|---|
| **Account invitation + password reset** | Accounts exist only via `dev-scripts/manage.py`, and a user who forgets their password cannot recover it. Needs a BAA-covered email provider (Postmark, SES) — note that even an invitation email is arguably PHI-adjacent, since it reveals a treatment relationship. |
| **Per-user timezone** | Session times are stored UTC and entered as naive local, so a therapist booking 15:00 gets 15:00 UTC. Correct storage, wrong experience. |
| **Tailwind precompiled** | `base.html` loads Tailwind from a CDN. That is a third-party request on a page rendering PHI, and the CSP has to name the CDN host to permit it. Building the CSS is what unlocks the strict policy in `app/security/headers.py` (`TARGET_CSP`) — run it with `CSP_REPORT_ONLY=1` first to see the violations. |
| **Rate limiting** | Only login is throttled, per (tenant, email). Nothing limits request volume generally. |

## 3. Decided but not built

From `docs/DECISIONS.md`, these have an answer but no implementation:

- **Claims (M7)** — an API-first billing partner (Candid Health / Stedi / Claim MD
  class). The data model is claims-shaped already; the integration is not built.
  Credentialing is an operational business, not just a schema.
- **Video visits (M6)** and **messaging (M5)** — BAA-covered vendors, chosen but
  not selected by name, integrated, or contracted.

## 4. Configuration reference

Everything is environment-driven; see `.env.example`.

```bash
APP_ENV=production              # anything but "dev" fails closed on missing secrets
SECRET_KEY=<32+ random bytes>   # required outside dev
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/care
TENANT_HOST_SUFFIX=example.com  # acme.example.com -> tenant "acme"
SESSION_IDLE_TIMEOUT_MINUTES=30
SESSION_ABSOLUTE_TIMEOUT_HOURS=12
LOGIN_MAX_ATTEMPTS=5
LOGIN_LOCKOUT_MINUTES=15
```

`APP_ENV=dev` relaxes exactly two things: cookies are not marked `Secure` (no
local TLS), and tenant resolution falls back to `DEV_DEFAULT_TENANT_SLUG`.
Anything else is treated as a real environment.

Migrations run on startup (`app/db_init.run_migrations()`), so a deploy applies
them automatically. With more than one instance, run migrations as a separate
release step instead — concurrent `alembic upgrade head` on boot is a race.

## 5. First-run provisioning

There is no self-service signup; the platform is sold to networks and accounts
are provisioned for people.

```bash
.venv/bin/python dev-scripts/manage.py create-tenant --name "Acme" --slug acme
.venv/bin/python dev-scripts/manage.py create-user --tenant acme \
    --email admin@acme.example --role admin
```

Then sign in as that admin at `acme.<TENANT_HOST_SUFFIX>` and use
**Administration → Therapists** for the rest.
