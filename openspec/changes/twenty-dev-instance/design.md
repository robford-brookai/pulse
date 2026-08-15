## Context

See `proposal.md` — Why. The full findings this design rests on, including the source
citations in Twenty's server code, are in
`.planning/reports/2026-08-14-dna-909-twenty-dev-instance-plan.md`.

Constraints that shape the approach, all verified read-only against the live tenant:

- **Tenant is EKS `duploinfra-nonprod`, namespace `duploservices-dev01-brook`.** The shared ALB's
  ACM certificate covers no hostname we would want, the tenant role is denied `route53:*` and
  `acm:*`, and EC2 writes are read-only — so anything needing DNS or a certificate is an admin
  step, not an agent step.
- **RDS `duplodev01-brook-dev` is Postgres 16.13, private, `db.t3.small`.** Its security group
  admits a VPN /32 and two public subnets today; the EKS node SG is confirmed absent and must be
  added. Twenty needs plain `postgres:16` with no exotic extensions, so this instance is
  sufficient.
- **`duploctl` requires an interactive portal token.** `duplo-jit` mints one without a TTY;
  `duploctl --interactive` blocks and dies under any agent harness. Every scripted path uses the
  former.
- **Upstream ships k8s manifests and a Helm chart.** The deploy is configuration of those, not
  hand-written manifests.

## Goals / Non-Goals

**Goals:**

- A running Twenty dev instance whose real contract is captured as committed fixtures, so the
  repo stops guessing.
- An answer, recorded either way, to whether `universalIdentifier` round-trips through the
  Metadata API — because the metadata deploy path's idempotency depends on it.
- A literal kanban drag in the UI that commits one correctly-timed ledger event, and a replay
  that commits none.

**Non-Goals:**

- The promotion path and multi-environment matrix. Dev only; `environment-matrix` is a later
  change.
- Closing ADR-0004 D14. This deploys dev to EKS and explicitly leaves SPCS-vs-EKS for production
  open.
- Production-grade capacity. `db.t3.small` shared across Twenty, its worker, and the ledger is
  adequate for a synthetic population of tens to hundreds and is expected to be revisited.

## Decisions

**Probe `universalIdentifier` before building anything on it.**
`universalIdentifier` is annotated `@HideField()` on Twenty's create-object input, and the REST
metadata API wraps the same resolvers — so it may be populated only by the app-sync path. If it
does not round-trip, the artifact's UUIDs are dropped on create and a second deploy run creates
duplicates instead of no-ops, which means `twenty:deploy` is superseded by `app:publish` for the
whole model. Everything after the probe is gated on its result. *Alternative considered:* deploy
the artifact first and infer the answer from whether a second run is a no-op. Rejected — it
answers the same question later, after work has been built on the assumption, and leaves a
duplicated model to clean up.

**Adapt to Twenty's signing scheme rather than translating to ours.**
Twenty's sender signs in a fixed format with no configuration hook, so a shim would be a
permanent translation layer maintained on our side for a contract we do not control. We change
our verifier instead. *Alternative considered:* a compatibility flag accepting both formats.
Rejected — it doubles the authentication surface to keep a format nothing will ever send again.
What survives unchanged is everything format-independent: the freshness window, constant-time
comparison, and dual-secret rotation.

**Derive logical time from the record's own update timestamp.**
Twenty sends no per-delivery event id: `webhookId` is per-webhook, `eventDate` per-batch, and the
nonce is regenerated per delivery attempt — precisely the opposite of an idempotency key.
`record.updatedAt` is stable across redeliveries of one write and distinct for a genuine second
drag, which is exactly the property an idempotency key needs. *Alternative considered:* hashing
the whole payload. Rejected — the nonce and timestamp are in the payload, so every redelivery
would hash differently and replay protection would silently do nothing.

**Denormalize the canonical identifiers onto the board object.**
The webhook's `record` is `properties.after`, the flat ORM entity: related objects appear as
foreign-key scalars, so a nested canonical path cannot resolve. Adding `canonicalPatientId` and
`programCode` as TEXT fields makes resolution a payload read. Both are pseudonymous identifiers,
not PHI. *Alternative considered:* a REST read-back per drag to fetch the related records.
Rejected — it puts a second credential and a new failure mode on the hot path, for data the
payload could simply carry.

**Refuse rather than guess an effective time.**
A UI drag updates the status field only; nothing stamps a status as-of field. Without a rule, the
projection would inherit the previous event's timestamp — a wrong time on a well-formed event,
which never raises and is therefore never noticed. The spec makes this a refusal instead. The
seed loader guarantees every board record lands with a non-null as-of stamp so the refusal path
is not the common case.

**Keep the command API cluster-internal.**
Twenty reaches it over a ClusterIP service name. It is HMAC-authed, holds no PHI in dev, and
nothing outside the cluster calls it — so it needs no ALB rule, hostname, or certificate, which
keeps Route53/ACM off the critical path and avoids editing a listener several unrelated tenant
services depend on. It also matters that the webhook route answers 200 to a broad class of
unauthenticated-looking traffic by design, so that Twenty stops redelivering unprocessable
payloads; that behavior is safe on a cluster-internal address and unwise on a public one. The
cost is that it cannot be curled from a laptop — use a port-forward.

**Split the database roles, and keep migration out of the pod lifecycle.**
Migration 0001 already creates a NOLOGIN group role carrying the append-only posture. The serving
role is a login role owning nothing that inherits it, so it physically cannot run DDL or mutate
the ledger. Migrations run as a separate role from the existing in-tenant Orca host, which can
reach the private RDS. *Alternative considered:* an init container. Rejected — it hands the API
pod a DDL-capable credential and dissolves the split it is meant to enforce.

**Sequence the `define.ts` shape change before the SDK dependency.**
`twenty-sdk` wants node `^24.5.0` and TypeScript `^5.9.3` against this repo's node `>=22` and
`typescript@7.0.2`. Reshaping the local stand-in to mirror `ViewManifestType` first is offline and
adds no dependency; adopting the SDK afterwards becomes a change of import path. Landing both at
once would make a type-checking failure ambiguous between the two causes.

**Seed from a committed deterministic projection.**
The synthetic-population generator emits into an untracked tree, needs a Java toolchain and a
500-patient run, and produces no canonical spine identifier — that is identity resolution's
output, minted deterministically from the generator's own record id. A committed, checksummed
projection makes seeding reproducible from a fresh clone with no toolchain.

## Data Model and API Surface

**Model change.** `patientProgram` gains `canonicalPatientId` and `programCode` as TEXT. Both flow
through the existing generate → mint-UID → validate path; the UID map is a reviewed diff, and
model keys must be added before minting because the map check fails on any key the model does not
ask for.

**View manifest.** Views become a real manifest type: `TABLE | LIST | KANBAN | CALENDAR`, grouped
by a field's universal identifier, referencing objects and fields by UUID and never by name, with
every view, view field, filter, sort, and group carrying its own identifier. A view is unreachable
from the sidebar without a navigation menu item, so the board ships with one — for a demo whose
point is dragging a card, unreachable equals nonexistent.

**Webhook registration.** Registered through the metadata GraphQL mutation, not the app manifest —
there is no manifest webhook type. Operations are narrowed to the mapped object's `.updated` event
rather than the default wildcard. The secret is client-supplied, so it is set equal to the
configured webhook secret and quarterly rotation still works through the update mutation.

**New task targets.** `ledger:image`, `ledger:migrate`, `ledger:deploy`, `twenty:app:build`,
`twenty:app:publish`, `twenty:seed` — all credentialed, all unreachable from `check`, enforced by
extending the existing reachability test.

## Risks / Trade-offs

- **`universalIdentifier` may not be settable** → Probed first, before anything is built on it.
  Bounded because the artifact has not been applied anywhere yet, so a negative answer costs a
  re-plan rather than a cleanup.
- **Relation, role, and comment endpoint shapes are unverified guesses**, as is the response
  envelope → A dry run precedes the first apply; these settle together on first contact.
- **Whether Twenty retries, and whether a retry re-signs with a fresh timestamp**, determines
  whether the record's update timestamp suffices as an idempotency source → Establish it from an
  observed redelivery, not from reasoning about the source.
- **Two TypeScript majors in one lockfile** → Sequence the shape change before the dependency, and
  import types only at first, so a failure is attributable.
- **Disabling the SSRF guard** is required for a private-IP webhook target → Dev-only and
  synthetic-only, but recorded in the runbook rather than left as an undocumented environment
  variable.
- **Duplo reconciliation may fight resources it does not own** → Confirm whether the instance
  should be a Duplo Service or raw manifests in the tenant namespace *before* applying; it is the
  difference between a stable instance and one that reverts.
- **Five unverified Duplo/AWS facts** — EKS-linux agent platform value, ClusterIP load-balancer
  type, docker-config key casing, ECR repo creation, and RDS ingress for the node SG → Each is a
  one-look confirmation, and getting one wrong is a rejected API call rather than a broken deploy.
  They are Phase A tasks precisely so they fail cheaply and early.
- **Shared `db.t3.small`** hosting Twenty, its worker, and the ledger → Adequate at this
  population size; watch it rather than pre-optimize.

## Migration Plan

Provision, probe, then build. Phase A stands the instance up and answers the
`universalIdentifier` question; nothing downstream starts until that answer is recorded. The
offline workstreams — serving layer, view-manifest reshape, seed loader — do not depend on the
answer and proceed in parallel.

The webhook contract change and the re-cut fixtures are a matched pair. They land together or the
suite is red; reverting one without the other is not a valid state.

**Rollback.** Delete the EKS workloads and drop the `twenty` database; nothing else depends on the
instance, and the ledger is append-only and synthetic, so nothing is lost. Metadata operations
never delete, so a failed apply leaves the workspace as it was rather than half-torn-down. Two
changes outlive a rollback and must be reverted deliberately: the RDS security-group ingress for
the EKS node SG, and the disabled SSRF guard.

## Open Questions

- Whether the shared `db.t3.small` remains appropriate once the synthetic population grows beyond
  a few hundred patients. Deferrable: it changes an instance size, not the specs or the approach.
- Whether production Twenty lands on SPCS or EKS. Explicitly deferred — ADR-0004 D14 stays open,
  and this change must say so in its runbook rather than settle it by precedent.
