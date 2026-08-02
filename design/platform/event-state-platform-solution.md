# PULSE — Solution Overview

**PULSE: Patient Unified Ledger of State & Events.** Brook's declarative event-state platform. (The name is reclaimed from the retired 2026-07 PULSE docs; this artifact set supersedes them.)

| | |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-07-28 |
| **Owner** | Rob Ford, Data |
| **Related** | twenty-licensing-structure-check.md; pulse-app-scaffold.md |

## The problem

Brook has no single, trusted answer to "what state is this patient (or provider, or clinic) in right now, and how did it get there?" Lifecycle facts — registered, enrolled, activated — live scattered across the systems that produced them. Every report re-derives state differently; discrepancies are found late, in analytics, with no audit trail to resolve them.

## The solution

A shared platform where systems **declare business facts as events** and everyone reads **one canonical current state**.

1. Any system reports a fact by making one API call: *what happened* (`patient-enrolled`), *to whom*, *when*, plus supporting detail.
2. Every event is stored permanently as an audit trail — nothing is overwritten.
3. Each entity's current state is updated from its latest event and visible to humans in a CRM-style interface.
4. All events and states land in Snowflake automatically for analytics and reconciliation.

## How it's built — deliberately not from scratch

The platform runs on **Twenty**, an open-source CRM (47k GitHub stars, active development), self-hosted in Brook's HIPAA-compliant infrastructure. Twenty provides out of the box: custom objects, a REST/GraphQL API for event ingestion, webhooks to notify downstream systems, role-based permissions, and a Postgres database that replicates to Snowflake with standard tooling.

Brook's customizations live in **`pulse-app`** — a small TypeScript package built with Twenty's official Apps framework, which declares the data model (objects, fields, relations, roles) and one server-side function that projects events onto current state. It installs into a stock, unmodified Twenty server; Twenty itself is never forked or patched.

**Custom code required: minimal and bounded** — roughly a hundred lines of tested TypeScript for the projection, plus declarative model definitions. Everything else is configuration. For a three-person data team, this is the decisive factor: the alternative (a bespoke event service) is buildable but becomes a permanent operational obligation. Here there is no service to run — the code executes inside Twenty.

## What each audience gets

- **Operations / clinical teams**: one screen showing any patient's current status and full event history, with the ability to spot and correct errors.
- **Engineering / partner systems**: one documented API to report events; webhooks to react to state changes. No point-to-point integrations.
- **Data / analytics**: complete, timestamped event history in Snowflake. State is reproducible from events; discrepancies become detectable and explainable.
- **Compliance**: immutable-by-policy audit trail, self-hosted (no PHI leaves Brook infrastructure, no vendor BAA required for the CRM itself), source-available software, every write attributable.

## Costs and risks

- **License**: $0 (AGPL-3.0, self-hosted, core unmodified). Microsoft SSO is included in the free core via Microsoft OAuth login backed by Entra ID; the paid enterprise tier is needed only if SAML is later mandated.
- **Infrastructure**: the POCAR migration program has selected **Snowpark Container Services + Snowflake Postgres**, keeping the deployment inside the existing Snowflake BAA perimeter. Estimated $175–350/month for the compute pool; Snowflake analytics side is negligible at confirmed volumes.
- **Known limits**: confirmed event volume (low thousands/day) is comfortably within capacity; duplicate-event protection is handled downstream in Snowflake rather than enforced at the API. If volume ever outgrows Twenty, only the ingestion leg is replaced — the event format, state model, and Snowflake layer carry over unchanged.
- **Upgrade discipline**: the Twenty image is version-pinned and upgrades are deliberate, tested events — the app declares against a schema that upstream migrations can touch.

## Scope

**MVP**: Patient, Program, PatientProgram, Provider, Clinic, DomainEvent objects; core lifecycle events (registered, enrolled, activated); event ingestion via the program's single MCP write path; projection logic function; Snowflake sync; state screens.

**Pilot producer — the signal adapter**: rather than waiting for source applications to emit events natively, day one runs a signal adapter that taps existing systems (PAP, Billy, POCAR, Customer.io) and translates observed side effects into declared events with system attribution and source evidence. Historical state backfills through the same path, so reporting starts on real data immediately. Native emission replaces the adapter one event type at a time.

**Compliance gate (program control C1)**: Twenty carries synthetic patient records only until Snowflake Postgres reaches GA with written BAA scope confirmation. Build, adapter, and Snowflake pipeline all proceed against synthetic data; real patient rows flip on when the gate clears. Dev/staging may run against a non-Snowflake managed Postgres to avoid blocking — decide before writing the SPCS service spec.

**Deferred**: event payload schema enforcement (except derived events), outbound subscriptions beyond webhooks, invalid-transition rejection (flagged in Snowflake instead), additional entity types as the state catalog ratification refines them.

## Decision requested

Approve MVP build on self-hosted Twenty. Prerequisites resolved 2026-07-28: (1) Microsoft SSO — covered by free core at $0; (2) event volume — low thousands/day confirmed, within capacity; (3) deployment target — SPCS per the migration program. Open gate: C1 (Snowflake Postgres GA + BAA scope) determines when real patient data enters.
