# The care platform — concept, name, and integration

The second product, framed as its own thing. Separate repo, separate deployment,
separate brand decision. It works *in conjunction with* Breakout Billing rather
than growing out of it.

Status: concept. Nothing built. Written 2026-07-31.

## Prior art — read this before anything else

The "nonprofit BetterHelp" idea already exists at scale, and knowing its exact
shape changes what's worth building.

**[Open Path Psychotherapy Collective](https://openpathcollective.org/)** — a
501(c)(3) with a network described as 40,000 strong. Clients pay $40–70/session
($30 with student interns) after a one-time $65 membership; eligibility is
household income under $100k and no adequate mental-health coverage. Therapists
pay nothing to participate.

The critical detail: **Open Path is a directory, a membership, and a matching
service — not software.** It does not host video visits, does not provide an EHR,
and does not bill insurance. Member therapists bring their own tools. That is
precisely the gap Breakout Billing already sits in.

**[Grow Therapy](https://growtherapy.com/)** is the closest thing to the
full-stack vision — for-profit, and it does credentialing and insurance billing
on the therapist's behalf. That's the real competitor for "marketplace + therapist
tooling + claims," not BetterHelp.

**The strategic implication.** The differentiated slot is probably *not* another
nonprofit directory — that's occupied, by an incumbent with 40k therapists. It's
the **software and billing layer that such a network conspicuously lacks**. Serving
networks like Open Path is a materially different (and cheaper) business than
competing with them, and it reuses far more of what already exists.

Worth deciding deliberately, because it determines nearly everything downstream.

## The two products and the boundary between them

| | **Breakout Billing** | **The platform** |
|---|---|---|
| User | one therapist | a network of therapists + their clients |
| Runs | on a laptop | hosted, multi-tenant, under a BAA |
| Money | self-pay / out-of-network, superbills | insurance claims and/or sliding scale |
| Video | a link to the therapist's own room | in-product visits |
| Client sees | nothing — no client login | intake, scheduling, sessions, payments |

**The therapist is the shared user, and that's the actual integration
requirement.** A therapist may keep a private caseload in Breakout Billing *and*
take platform clients. Their books have to combine — one year-end income picture,
one A/R view. That, not code reuse, is what integration has to solve.

## Name

Two strategies. They imply different things.

**A — keep the family.** Suite: **Breakout Health**, containing *Breakout Billing*
(solo tool) and *Breakout Care* (platform).

- Cheap: no new brand equity, obvious relationship, one story to tell funders.
- Weak for consumers: a mental-health brand named after billing software is a
  liability, and "breakout" reads as acne or prison break to a client audience.
- Good fit if the platform is **infrastructure sold to networks and therapists**.
  Bad fit if clients see the brand.

**B — a distinct consumer brand with shared parentage.** Candidates, with what I
found:

| Candidate | Read | Collision check |
|---|---|---|
| **Even Keel** | calm, non-clinical, memorable, plain-English | nothing prominent surfaced in mental health |
| **Care Commons** | signals the collective / nonprofit model directly | generic; likely weak as a trademark |
| **Threshold Care** | crossing-over, access | not checked in depth |
| **Alongside** | "care alongside you" — warm, non-clinical | no prominent mental-health company surfaced; common word, so weak trademark and hard SEO |

**Ruled out:** *Throughline* — [ThroughLine](https://www.throughlinecare.com/) is an
existing mental-health crisis-helpline network *and* there's a separate
[ThroughLine between-sessions therapy app](https://www.throughlineapp.com/). Two
collisions in the exact category. *Beacon* (Beacon Health Options), *Open Path*
(the incumbent), *Lantern* and *Harbor* (used in health) are also out.

**Recommendation:** if this is infrastructure, use **Breakout Care** and spend
nothing on branding. If clients will see it, **Even Keel** is the strongest of the
above.

⚠️ I checked for obvious collisions via web search only. Before committing to any
name, run a USPTO trademark search and a domain check — I did not verify
trademark status or availability.

## How the integration works

Three layers, loosest coupling first. Build 1 and 2; defer 3.

### 1. A shared domain library — `breakout-core`

Extract from the existing repo and publish as a versioned Python package that both
products depend on:

- the domain model — `Client`, `Appointment`, `Payment`, `Provider`
- superbill PDF generation (`app/superbill.py`)
- the CPT catalog (`app/cpt.py`)
- the money math (`app/finances.py`)
- the CSV importer (`app/importer.py`)

No runtime coupling, no network calls, no shared database. Most of this is already
cleanly isolated in the current repo, which is why it's the cheap, high-value step.

**One real caveat:** the models today are SQLAlchemy declarative classes on a
single `Base`, carrying single-tenant assumptions. Extraction means either
splitting pure domain logic from the ORM layer (more work, correct) or shipping the
ORM models and letting the platform bolt a tenant column on (fast, and it will
hurt later). Prefer the first.

### 2. A documented JSON export/import contract

The therapist-portability path, and the honest answer to "own your data" for
platform users.

- The platform exports a therapist's encounters and payments; the local tool
  imports them.
- `app/importer.py` already establishes the column-matching pattern for clients —
  extend it to appointments and payments.
- **Platform → local is the direction that matters.** It's what lets a therapist
  leave without losing records, and what lets them do year-end books in one place.

### 3. Live API sync — defer

Turning the local app into an API client brings tokens and refresh, conflict
resolution, partial-failure states, and a support burden — on software whose main
virtue is that it runs on one laptop and needs nothing. Only worth building if
therapists genuinely run both systems against the same clients simultaneously.
That's an assumption to test, not to build on.

### Non-goals

- Breakout Billing must never *require* the platform. Standalone is its premise.
- No shared database between the two.
- Don't let platform PHI flow into the local tool casually. The local threat model
  assumes one user on one encrypted disk; a sync feature quietly widens it.

## Settle these before writing code

1. **Who is the customer — the client or the therapist network?** Consumer
   marketplace vs. infrastructure. Everything else follows from this.
2. **Insurance claims, or sliding-scale cash?** Claims plus per-therapist,
   per-payer, per-state credentialing is the single largest cost in the whole
   plan. Open Path's sliding-scale model sidesteps it entirely.
3. **Does the nonprofit employ therapists or list them?** Employment brings
   supervision, liability, and payroll.
4. **Which states at launch?** Licensure is per-state; it bounds the launch more
   than engineering does.

## Sources

- [Open Path Psychotherapy Collective](https://openpathcollective.org/)
- [Open Path — pricing & eligibility](https://openpathcollective.org/pricing-and-eligibility-for-affordable-therapy/)
- [Open Path — Wikipedia](https://en.wikipedia.org/wiki/Open_Path_Collective)
- [Grow Therapy — best online therapy comparison](https://growtherapy.com/blog/best-online-therapy/)
- [ThroughLine (crisis network)](https://www.throughlinecare.com/)
- [ThroughLine app (between sessions)](https://www.throughlineapp.com/)
