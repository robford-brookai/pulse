## Purpose

Provide a repeatable Engineering demonstration of source connectors, immutable ledger APIs, operational projections, and resumable batch hydration with an isolated demo reset.

## ADDED Requirements

### Requirement: Verified source contracts

The demo SHALL use POCAR as its primary source and PAP as its second source. Before implementing each connector mapping, discovery SHALL record the available MCP metadata, approved read-only access method, source grain, identity keys, supported state and event semantics, and evidence limitations. Discovery SHALL NOT expose PHI through external MCP services, repository artifacts, or demo receipts; missing access or mappings SHALL remain explicit blockers.

#### Scenario: Source mapping is established before implementation
- **GIVEN** a source has not yet supplied a verified mapping
- **WHEN** its connector is prepared for implementation
- **THEN** a reviewed metadata-only contract identifies one bounded event family, identities, provenance, and supported commands, or implementation is blocked with the missing evidence named
- **AND** POCAR and PAP each require their own contract without inferred collection or field names

### Requirement: Connector creation and ledger reads use APIs

For each source, the demo SHALL show creation through the authorized Pulse command API and retrieval of resulting state and event history through Pulse read APIs. Requests and responses SHALL expose the correlation between source evidence, accepted command, ledger event, and derived state without bypassing existing identity, authorization, or transition rules.

#### Scenario: POCAR creation and read round trip
- **GIVEN** a verified POCAR mapping and a valid representative source record
- **WHEN** the connector submits its create command and the demo reads the resulting subject through the state and history APIs
- **THEN** the responses identify the accepted event and derived state with source provenance and matching subject identity

#### Scenario: PAP creation and read round trip
- **GIVEN** a verified PAP mapping and a valid representative source record
- **WHEN** the connector submits its create command and the demo reads the resulting subject through the state and history APIs
- **THEN** the responses identify the accepted event and derived state with source provenance and matching subject identity

### Requirement: Immutable history remains observable

The demo SHALL prove append-only behavior using a supported transition or correction, exact retries, and conflicting idempotency keys. A correction SHALL follow the existing catalog contract rather than modifying a previously accepted event.

#### Scenario: Transition preserves the original event
- **GIVEN** an accepted event and its captured API representation
- **WHEN** a supported transition or correction is submitted and history is reread
- **THEN** a new event explains the changed derived state and the original event content remains unchanged

#### Scenario: Retry and conflicting key are distinguishable
- **GIVEN** an accepted command with a deterministic idempotency key
- **WHEN** the identical command is retried and a different command is submitted with that same key
- **THEN** the retry adds no event and the conflicting command is rejected without changing history or state

### Requirement: Twenty reflects connector semantics

Twenty SHALL present objects, relationships, current state, and key events derived from the verified connector contracts. Its views SHALL retain source and ledger provenance, expose projection freshness, and treat Pulse as the state authority. Any supported Twenty mutation SHALL use Pulse commands and SHALL NOT independently establish authoritative state.

#### Scenario: Twenty displays state and event lineage
- **GIVEN** accepted POCAR and PAP events with their verified relationships
- **WHEN** their projections converge
- **THEN** Twenty displays the mapped operational state, relationships, and key-event history linked to the corresponding ledger subjects and events
- **AND** delayed projection delivery is visible as stale or pending rather than presented as current

### Requirement: Batch seed and historical backfill preserve evidence

Batch hydration SHALL distinguish current-state seeding at a declared cutoff from historical reconstruction. Both SHALL write through authorized command APIs with deterministic keys, versioned mapping or adjudication rules, and source evidence references. Historical events SHALL distinguish effective time from recording time; unavailable history SHALL NOT be fabricated. Ambiguous identity, unsupported state, or insufficient evidence SHALL be quarantined with reviewable reasons.

#### Scenario: Current seed and history remain distinguishable
- **GIVEN** a bounded source snapshot and evidence-backed historical records
- **WHEN** current-state seeding and historical backfill run
- **THEN** API history identifies the cutoff, evidence provenance, rule version, and effective and recorded times appropriate to each accepted event
- **AND** missing historical evidence is reported as a gap rather than an invented transition

#### Scenario: Ambiguous records are quarantined
- **GIVEN** a batch containing ambiguous identities and records without sufficient state evidence
- **WHEN** the batch is processed
- **THEN** those records produce no unsupported ledger events and receive reviewable quarantine reasons while valid records remain accounted for

#### Scenario: Interrupted batch resumes without duplicate events
- **GIVEN** a batch interrupted after some commands were accepted but before all progress was acknowledged
- **WHEN** the same batch resumes from its durable progress and retries uncertain outcomes
- **THEN** accepted commands are not duplicated and input totals reconcile to accepted, quarantined, or explicitly failed records with no silent omissions

### Requirement: Engineering presentation connects record detail to operations

The runnable demo SHALL provide a coherent progression between one record's source-to-ledger-to-Twenty trace and cohort operations. Operations SHALL include batch progress, throughput, retries, quarantine, projection lag, and reconciliation. Step results SHALL come from executable assertions against actual responses and observed state; failures SHALL produce actionable receipts and a nonzero exit rather than a simulated success.

#### Scenario: Record drilldown and cohort operations share evidence
- **GIVEN** an executing representative batch
- **WHEN** the presenter moves between cohort operations and a selected record
- **THEN** both views use the same run and subject correlation, and displayed counts and outcomes reconcile with the execution receipt

#### Scenario: Demonstration failure is visible and reproducible
- **GIVEN** an injected synthetic invalid transition or downstream delivery failure
- **WHEN** the relevant demo stage executes
- **THEN** the rejection or recovery behavior is asserted, and an unexpected outcome ends the run unsuccessfully with redacted reproduction context

### Requirement: Projection recovery proves ledger durability

The demo SHALL separately demonstrate reconstruction of a disposable projection from the retained ledger. Recovery SHALL preserve the ledger and compare reconstructed state and relationships against the pre-rebuild result.

#### Scenario: Projection rebuild recovers equivalent state
- **GIVEN** a converged demo projection and captured ledger history
- **WHEN** that projection is cleared and rebuilt from the ledger
- **THEN** its state and relationships match the pre-rebuild result and ledger history remains unchanged

### Requirement: Demo reset is isolated and complete

Reset SHALL be restricted to an explicitly enabled disposable demo target with a reviewed ownership manifest covering every data-bearing component and delivery path. It SHALL fence producers and stale delivery before clearing run-owned ledger, projections, identity state, idempotency state, queues, and checkpoints. Reset SHALL refuse shared or authoritative targets, retain only the declared redacted audit receipt outside the reset scope, and verify zero data across the manifest before reporting success. Fresh hydration SHALL use a new run identity and SHALL NOT accept late deliveries from the prior run.

#### Scenario: Reset refuses an unsafe target
- **GIVEN** demo mode is disabled or any target ownership, isolation, or delivery-fencing prerequisite is unverified
- **WHEN** reset is requested
- **THEN** reset refuses before deleting data and identifies the failed prerequisite

#### Scenario: Reset reaches zero and permits clean reload
- **GIVEN** a populated manifest-owned demo environment with a verified delivery fence
- **WHEN** reset clears its data and a fresh run hydrates it again
- **THEN** zero checks pass for every manifest component before reload, the fresh run completes its API and projection assertions, and delayed prior-run deliveries cannot repopulate the environment
- **AND** source systems and the authoritative ledger remain unchanged

### Requirement: Synthetic demonstration and real-data rehearsal share contracts

The Engineering demonstration SHALL be runnable with representative synthetic data through the same connector mappings and batch contracts used for a bounded real-data rehearsal. Real-data execution SHALL remain attended within the approved data boundary using approved read-only source access and isolated targets. Shared presentation artifacts, tests, and receipts SHALL contain no PHI. Existing supported demo commands SHALL remain available until replacement acceptance succeeds.

#### Scenario: Rehearsal uses the same verified integration path
- **GIVEN** successful synthetic acceptance and approved real-data source access, cohort, and isolated target
- **WHEN** an attended real-data rehearsal executes
- **THEN** it uses the same verified connector mappings, command and read APIs, and batch recovery assertions while retaining sensitive data within the approved boundary
- **AND** absent prerequisites block the real-data run without preventing synthetic execution
