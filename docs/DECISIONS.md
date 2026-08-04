# Decisions to settle before building features

The concept note (`CONCEPT.md`) is blunt: some of these determine "nearly
everything downstream." Answer the product questions before writing feature code;
record the answers here as they're made.

## Product (settle first — they drive the data model and stack)

1. **Who is the customer — the client, or the therapist network?**
   Consumer marketplace vs. infrastructure sold to networks/therapists. The
   concept note argues the differentiated slot is the **software + billing layer**
   that nonprofit networks (e.g. Open Path) conspicuously lack — a cheaper, more
   reusable business than competing as another directory. _Decision: TBD._

2. **Insurance claims, or sliding-scale cash?**
   Claims + per-therapist/per-payer/per-state credentialing is the single largest
   cost in the whole plan. Open Path's sliding-scale model sidesteps it.
   _Decision: TBD._

3. **Does the org employ therapists, or list them?**
   Employment brings supervision, liability, and payroll. _Decision: TBD._

4. **Which states at launch?**
   Licensure is per-state; it bounds launch more than engineering does.
   _Decision: TBD._

## Downstream (follow from the above)

- **In-product video visits?** A real build (WebRTC/vendor, recording/retention,
  BAA). The concept table lists in-product visits as a platform trait, but it's
  not assumed — telehealth was explicitly dropped from Breakout Billing.
  _Decision: TBD._
- **Client-facing surface.** Intake, scheduling, sessions, payments — how much
  ships in v1? _Decision: TBD._
- **Name & brand.** *Breakout Care* (infra, no branding spend) vs *Even Keel*
  (consumer). Run USPTO + domain checks first. _Decision: TBD._
- **License.** Depends on the business model (see README). _Decision: TBD._
- **Frontend.** Start with HTMX+Jinja (reuses Billing's approach and
  `breakout-core`); revisit only if a polished consumer portal / video is
  central. _Working default: HTMX+Jinja._

## Foundation (true regardless of the above — build early)

- Real multi-user auth with **client / therapist / admin** roles.
- **Tenant isolation** on every query (`tenant_id` everywhere; see `CLAUDE.md`).
- Timezone-aware datetimes (Billing uses naive local; the platform can't).
- Audit logging of PHI access; CSRF; TLS; BAA-covered host + comms provider.
- The **`breakout-core`** dependency boundary (`INTEGRATION.md`) — don't
  re-implement the shared domain here.
