## Context

runtime-readiness §§1.5 and 3.3 define three SLOs and severities. September 8 shipped the cheap half: liveness/readiness and tagging. `reconciliation-sweeps` implements the comparison core and awaits its attended first run; this change consumes it instead of creating another sweep.

## Goals / Non-Goals

**Goals:** Detect stopped/stale services and prove recovery with usable operator evidence.

**Non-Goals:** Reimplementing shipped liveness probes, assigning a person without confirmation, sending messages during proposal filing, or treating synthetic drills as monthly production SLO compliance.

## Decisions

### 1. Keep the existing SLO boundary

Availability is 99.9% monthly, command commit latency p99 < 500 ms, and ledger-to-Twenty freshness
p99 < 60 s. Outbox age is a diagnostic sub-budget, not a fourth SLO and not a percentile of completed
deliveries. Measure latency/freshness distributions with defined event timestamps, success/failure
denominators and no-data states; idle consumers are not failed consumers. Use the existing queue and
worker health signals rather than a second heartbeat protocol.

### 2. Launch monitor coverage and routing

Cover API errors/latency, outbox lag and DLQ, consumer freshness, verdict-run staleness (>26 h), missed
month-open, reconciliation drift, and quarantine depth/age. Each definition includes environment,
service, project, severity, owner-role and a runbook link. DLQ depth >=1 alerts; sustained >15 min
uses the page policy in §3.3. Production paging is business-hours before P2 and follows the cutover
policy afterward. Staging alerts route only to the verified non-paging destination; dev remains
traces-only unless an attended isolated drill explicitly enables its test monitor. A missing owner
or destination blocks live activation, not offline definition tests.

### 3. Recovery drill and receipt

First compare deployed image digests, migrations and probe definitions to the intended release.
Then use an isolated synthetic subject/queue in dev or staging: token-expiry simulation, halted/wedged
consumer, dependency outage and outbox backlog. Assert the configured detection window, unhealthy
state, signal delivery, no early queue acknowledgement, resumed processing, duplicate suppression,
and conformance after recovery. Never revoke a shared real credential to simulate expiry. Abort on
unexpected impact outside the test scope. One attended session per bounded fault family; ongoing
reconciliation belongs to the existing change and is referenced by receipt, not re-run as a new plan.

### 4. Data and APIs

Monitor configuration is versioned IaC using the repo's existing deployment conventions; do not
invent a second infrastructure owner. Receipts contain commit/image digest, environment, probe/fault
identifier, timestamps, counts, expected threshold, outcome and evidence link. Synthetic identifiers
only; no raw exceptions, credentials or payloads. Propagate the existing trace/correlation identifier
through writes and consumes and test redaction. Proposed 2026-09-10; owner request resumes planning
of queued observability, while live activation and cutover prerequisites remain intact.

## Risks / Trade-offs

[No-data appears healthy] → test absent and stale telemetry separately from idle traffic. [Drill impacts shared dev] → isolate synthetic queue/subject, bounded faults and cleanup. [Owner rotation unfilled] → record unresolved activation prerequisite instead of inventing a recipient.

## Migration Plan

Merge emitters, definitions and runbooks; validate config offline; activate only in an attended session with verified owner/destination and release manifest. Run bounded drills and store receipts. Production paging activation follows the existing cutover ladder. Roll back configuration independently of application state.
