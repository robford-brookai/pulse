# customerio-consent-ingress Specification

## Purpose
Declares Customer.io's delivered consent landing (Snowflake `streamline.cio_raw`/`cio_prod`) as
attributed, provenance-carrying `record_communication_consent` commands on the ledger's single
write path — D9's forward consent ingress, the recording half of the consent story whose
correcting half is `consent-reconciliation`'s sweep.
## Requirements
### Requirement: Landed consent rows declare through the command API

The ingress SHALL read consent rows from the delivered `streamline.cio_raw`/`cio_prod` Snowflake
landing and declare one `record_communication_consent` command per row through the ledger's
command API client boundary. It SHALL NOT write to the ledger by any other path, and SHALL NOT
emit a catalog-state event as a producer — the ingress holds no catalog-state event vocabulary of
its own.

#### Scenario: A landed row becomes a command

- **GIVEN** a consent row on the `streamline.cio_raw`/`cio_prod` landing
- **WHEN** the ingress reads and declares it
- **THEN** exactly one `record_communication_consent` command is submitted through the command
  API client, and no other write path is used

### Requirement: The consent grain composes identically to the reconciliation sweep

`CommunicationConsent` is per patient × channel; the ledger's `current_state` keys one row per
`(subject_type, subject_key)` single string. The ingress SHALL compose that key as
`{subject_key}:{channel}` — the exact composition `consent-reconciliation`'s sweep already uses —
so the two paths, reading and writing the same landing, can never disagree on which row a
(subject, channel) pair owns.

#### Scenario: Ingress and sweep address the same row identically

- **GIVEN** a consent row for subject S on channel C landed via `streamline.cio_raw`/`cio_prod`
- **WHEN** the ingress declares a command for it
- **THEN** the declared command addresses ledger subject key `S:C`, the same key
  `consent-reconciliation`'s sweep would compute for the same (subject, channel) pair

### Requirement: Re-reading the same landing rows replays

The ingress SHALL derive each command's D16 idempotency key from the source row's own identity
(its message/event id and event time) — never wall-clock time at read time — so that re-reading
the same landing rows, whether from a cursor resume after a crash or a full re-run, classifies
every affected command as a replay rather than declaring it again.

#### Scenario: A cursor resume replays its last page

- **GIVEN** a crash between a page's declarations and its cursor commit
- **WHEN** the ingress resumes and re-reads that page
- **THEN** every row's re-declared command classifies as `replayed`, and no consent state is
  double-declared

#### Scenario: A full re-run over the same landing replays

- **GIVEN** the same landing rows read in a prior run
- **WHEN** the ingress runs again over the same rows with no new landing since
- **THEN** every command classifies as `replayed`

### Requirement: Malformed landing rows are counted and never dropped silently

A landing row that violates the pinned row contract (missing or malformed required column) SHALL
be counted and attached to the run's receipt with an identifying reference (never a raw contact
value) rather than aborting the run; the remaining rows in the same read SHALL still be declared.

#### Scenario: A malformed row among valid ones

- **GIVEN** a Snowflake read page containing malformed rows among valid ones
- **WHEN** the ingress runs
- **THEN** the valid rows are declared, the malformed rows are counted and attached to the
  receipt by reference, and none are dropped without a trace

### Requirement: Receipts and logs carry no contact values

Every receipt and log line the ingress emits SHALL carry subject keys and channel names only —
never contact identifiers (email address, phone number) or any other contact value from the
`cio_raw`/`cio_prod` landing.

#### Scenario: A run receipt is safe to attach to logs

- **GIVEN** a completed ingress run over rows carrying contact identifiers
- **WHEN** the run's receipt is emitted
- **THEN** the receipt contains subject keys, channel names, and counts only — no contact value
  from any row appears in the receipt or in any log line the run produced

### Requirement: Every Snowflake read is fixture-faked in tests

The ingress's Snowflake read SHALL be abstracted at a `RowSource`-style boundary substitutable by
a fixture in every test. No test SHALL open a live network connection; the full test suite SHALL
pass under `--disable-socket`.

#### Scenario: The test suite runs with no live network

- **WHEN** the ingress's test suite runs under `--disable-socket`
- **THEN** every test passes using a fixture-backed row source, with no live Snowflake connection
  attempted

### Requirement: Every declaration attributes to actor `customer-io`

Every command the ingress declares SHALL attribute to actor `customer-io` by virtue of the
per-service credential the ingress authenticates with — never by a payload field naming the
actor (ADR-0003: attribution is authentication). The writer id is spelled `customer-io` because
the command API derives writer ids from `PULSE_LEDGER_WRITER_TOKEN_<SUFFIX>` by lowercasing the
suffix and mapping `_` to `-`, so the credential is registered as
`PULSE_LEDGER_WRITER_TOKEN_CUSTOMER_IO` (decision recorded 2026-09-02, `pulse-demo-closeout`
design.md decision 9). Every command's payload SHALL carry message-level provenance: a reference
to the source landing row (its message or event identifier) sufficient to trace a recorded
consent state back to the Customer.io message that produced it.

#### Scenario: A declared command is customer.io-attributed and traceable

- **GIVEN** a consent row read from the landing
- **WHEN** the ingress declares it
- **THEN** the command is submitted under the ingress's own `customer-io` service credential, and
  its payload references the source row's message/event identifier

#### Scenario: The writer id round-trips through the registry's suffix mapping

- **GIVEN** a credential registered as `PULSE_LEDGER_WRITER_TOKEN_CUSTOMER_IO`
- **WHEN** the API resolves the writer id from that variable name
- **THEN** the resolved id equals the ingress's declared writer id, `customer-io`, exactly

