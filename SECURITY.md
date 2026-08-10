# Security policy

This platform is designed to hold **protected health information (PHI)** for
multiple therapist networks. Please treat security reports accordingly.

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private vulnerability reporting
(Security → Report a vulnerability) on this repository, or email the maintainer.

Please include what you did, what happened, and what you expected. If you found
a way to read another tenant's data, say so first and in the subject line — that
is the failure mode this codebase cares most about.

We will acknowledge within a few days. There is no bounty programme.

## Current status — read before deploying

> **This software is not yet suitable for holding real PHI.** It is a working
> foundation, not a finished product. See `docs/DEPLOYMENT.md` for the specific
> gaps. Deploying it against real patient data today would be irresponsible.

## What is implemented

- **Tenant isolation** enforced in one place (`app/tenancy.py`). Routes cannot
  query tenant-owned tables without scoping; a model missing `tenant_id` raises
  rather than silently returning everything.
- **Authentication** — Argon2id password hashing, server-side sessions with
  idle and absolute timeouts, immediate revocation on logout, password change,
  or deactivation. Session tokens stored hashed.
- **Authorization** — `client` / `therapist` / `admin` roles; therapists are
  limited to their own caseload. Records outside a caller's scope return 404
  rather than 403, since a 403 confirms the record exists.
- **CSRF** on every state-changing request, registered app-wide so new routes are
  protected by default.
- **Audit logging** of authentication, authorization denials, and PHI access.
  Audit entries deliberately never contain PHI; there is a test asserting it.
- **Login throttling** per (tenant, email), with uniform failure messages so the
  login form cannot be used to enumerate accounts.
- **Download filenames are allowlisted**, not escaped (`app/downloads.py`).
  Client names reach `Content-Disposition`, and a quote in a name could
  otherwise inject header parameters or spoof the saved filename.
- **`next=` after login accepts only same-site relative paths**, rejecting
  scheme-relative and backslash forms.
- **A structural test asserts every route carries a role dependency** or is
  explicitly listed as public (`tests/test_security.py`), so a new unguarded
  route fails CI rather than waiting to be noticed.

## What is not yet implemented

- No TLS termination, secrets management, or backup/retention policy in this
  repo — those belong to the deployment.
- No BAA with any host, email, or SMS provider.
- No encryption of PHI at rest beyond whatever the database host provides.
- No email provider is configured, so invitation and password-reset links
  cannot actually be delivered. The flows themselves are built and tested.
- No rate limiting beyond login lockout.

## Reporting scope

In scope: tenant isolation failures, authentication and session handling, CSRF,
authorization boundaries, audit-log integrity, and anything that discloses PHI.

Out of scope: findings that require an attacker to already hold valid admin
credentials for the tenant in question, and issues in the deployment
configuration of a third party running this code.
