# Decisions

The concept note (`CONCEPT.md`) is blunt: some of these determine "nearly
everything downstream." The four product questions were settled **2026-08-06**;
the downstream items follow below, some still open.

## Product (settled 2026-08-06)

1. **Who is the customer — the client, or the therapist network?**
   **Decision: the therapist network — infrastructure, not a consumer
   marketplace.** Open Path is an incumbent directory with ~40k therapists and
   conspicuously no software; competing as another directory means fighting for
   therapist supply with a consumer CAC problem attached. The differentiated slot
   is the software + billing layer such networks lack.

   *Caveat carried forward:* the client-facing surface decided below (portal,
   video, chat) is substantial, so clients **do** see a product even though they
   aren't the customer. See "Client portal branding" under Downstream.

2. **Insurance claims, or sliding-scale cash?**
   **Decision: insurance claims — in scope, not deferred.** This overrides the
   earlier recommendation to launch sliding-scale-only. Claims is the single
   largest cost in the plan (per-therapist × per-payer × per-state credentialing
   is an operational business, not a feature), and it is also the strongest moat
   versus Open Path and the real competitive answer to Grow Therapy.

   *Sequencing:* claims lands late in the milestone plan, but the money model
   (`Charge` / `Payment` / `Claim`) is built claims-shaped from the first
   migration so nothing is rewritten when it arrives.

3. **Does the org employ therapists, or list them?**
   **Decision: list them.** Therapists are independent members of a tenant,
   carrying their own licensure and liability. No supervision, payroll, or
   malpractice surface. Follows from the infrastructure model in (1).

4. **Which states at launch?**
   **Decision: state-agnostic.** No fixed launch state set. Because therapists
   are listed rather than employed (3), licensure is the network's compliance
   obligation. The engineering residue is: store per-therapist state licenses,
   and validate client state against therapist licensure at booking time. That
   logic is built once and holds for any state set a network operates in.

## Scope (decided 2026-08-06, with the product answers)

The platform is a full practice system, not a thin billing layer:

- **Client portal** — document signing, intake forms, downloading billing
  documents.
- **In-product video visits.** *This reverses the working default.* Telehealth
  was dropped from Breakout Billing (owner's 2026-08-02 decision) and
  `START-HERE.md` says not to assume it here — it is now explicitly **in scope**
  for the platform.
- **HIPAA-compliant therapist ↔ client messaging.**
- **Billing** — Breakout Billing's feature set and considerably more, including
  insurance claim processing.
- **Clinical note-taking**, integrated (not a separate tool).
- **Therapist interface** and **administrator interface** as distinct surfaces.
- **Scale target:** multiple admins and thousands of therapists.
- **Security/HIPAA compliance throughout**, not retrofitted.

## Downstream

- **In-product video visits?** **Decided: yes** (see Scope). Build-vs-buy for the
  video/chat transport is tracked below.
- **Client-facing surface.** **Decided: substantial** — portal, forms, e-sign,
  document download, chat, and video. v1 cut line is set by the milestone plan,
  not by scope doubt.
- **Video / chat vendors.** **Decided 2026-08-06: BAA-covered vendors for both.**
  Video via a healthcare-BAA provider (Zoom Healthcare / Daily / Twilio); chat
  likewise rather than owning real-time infrastructure. The platform does not
  build WebRTC signaling or TURN. Each vendor must be under a BAA before any PHI
  crosses it — that gate is part of the milestone, not a follow-up.
- **Claims: build vs. buy.** **Decided 2026-08-06: API-first billing partner**
  (Candid Health / Stedi / Claim MD class), not direct clearinghouse EDI. The
  platform does not generate 837s or parse 835s itself; it models charges,
  claims, and remittances and delegates the wire format. Accepts per-claim cost
  and vendor lock-in to cut M7 from a quarter-scale project to a large feature.
- **Client portal branding.** **Decided 2026-08-06: white-labeled per tenant.**
  Each network's clients see that network's name and styling. This preserves the
  infrastructure posture — clients use the product without meeting a platform
  brand. Cost: per-tenant theming in the template layer, which the `Tenant` model
  must carry from early on.
- **Name & brand.** _Decision: TBD, but narrowed._ White-labeling means no
  consumer brand is required, so *Breakout Care* is the working name and *Even
  Keel* is effectively out of the running. Still run USPTO + domain checks before
  committing.
- **License.** **Decided 2026-08-08: AGPL-3.0**, matching Breakout Billing so the
  family is coherent. The reciprocity is the point: anyone hosting a modified
  version must publish their changes, which is the protection that matters when
  the business is selling this as a hosted service. Selling commercial
  exceptions remains available, since the copyright is held in one place.
- **Frontend.** HTMX+Jinja remains the working default. Video is a vendor SDK
  embed and chat can ride HTMX's SSE/WebSocket extensions, so neither forces a
  SPA. Revisit only if the client portal demands it.

## Foundation (true regardless of the above — build early)

- Real multi-user auth with **client / therapist / admin** roles.
- **Tenant isolation** on every query (`tenant_id` everywhere; see `CLAUDE.md`).
- Timezone-aware datetimes (Billing uses naive local; the platform can't).
- Audit logging of PHI access; CSRF; TLS; BAA-covered host + comms provider.
- The **`breakout-core`** dependency boundary (`INTEGRATION.md`) — don't
  re-implement the shared domain here.
