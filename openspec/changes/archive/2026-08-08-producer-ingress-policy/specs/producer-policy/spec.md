## Purpose

Enforces the §4.4 producer policy as an offline CI gate: no producer schema in `packages/ocean`
names a catalog state. State-asserting emits route through the ledger's command API; non-subject
facts keep emitting directly; the catalog is the boundary, checked mechanically on every run of
`task check`.

## ADDED Requirements

### Requirement: Producer schemas are classified against the catalog contract

The gate SHALL extract the declared event vocabulary of the producer source in `packages/ocean` —
state vocabularies (literal unions, enums, string sets), entity-type declarations, and event-type
addressing — and classify each element against the pinned catalog contract
(`catalog/state_catalog.yaml` at the repo head, read through its programmatic surface). An
element SHALL be flagged as state-asserting only when it addresses a catalog subject: it declares
an entity or subject type equal to a catalog subject, carries a state vocabulary that identifies
a catalog subject's declared state set, or constructs an event type that both carries a catalog
subject as its prefix and names one of that subject's declared states in its remaining segment
or accompanying payload — a subject-prefixed event type whose action word is not a catalog state
(`device.associated`) SHALL NOT flag. A vocabulary that merely reuses a bare word the catalog
also uses (`open`, `resolved`, `active`) while describing a non-subject entity SHALL NOT flag. Every finding SHALL name the
source file, the schema element, and the catalog subject and state(s) it asserts.

#### Scenario: A state-asserting producer schema is flagged

- **WHEN** a producer schema in `packages/ocean` declares an event addressing a catalog subject
  with a vocabulary naming that subject's states (e.g. a `referral` event carrying
  `screened`/`outreach`/`converted`)
- **THEN** classification returns a finding naming the file, the schema element, and the catalog
  subject and states asserted

#### Scenario: A non-subject fact schema passes

- **WHEN** a producer schema describes a non-subject fact (a reading landed, a call completed, a
  document arrived) addressing no catalog subject
- **THEN** classification returns no finding for it

#### Scenario: A bare-word name collision does not flag

- **WHEN** a producer vocabulary for a non-subject entity reuses bare words the catalog also uses
  (an alert status carrying `open` and `resolved`, a ticket status carrying `open` and
  `in_progress`) without addressing any catalog subject
- **THEN** classification returns no finding for it

### Requirement: The gate is enforced offline in task check

The producer-policy gate SHALL run under `task check` as an offline test — passing in a fresh
clone with no network and no credentials — classifying the committed producer source in
`packages/ocean` against the catalog contract, and SHALL read only the pinned contract surfaces:
the authoritative catalog file and its programmatic surface, never the retired seed, the
Snowflake rows, or generator internals. Any unsuppressed finding SHALL fail the check naming the
offending schema and the colliding subject and state(s); a tree with no findings passes.

#### Scenario: The current tree passes the gate

- **WHEN** `task check` runs on a tree whose producer schemas assert no catalog state
- **THEN** the producer-policy gate passes, offline, in a fresh clone

#### Scenario: A planted state-bearing emit turns the gate red, and removal turns it green

- **WHEN** a producer schema asserting a catalog subject's state transition is planted in
  `packages/ocean` and the gate runs, then the schema is removed and the gate runs again
- **THEN** the first run fails naming the planted schema and the asserted subject and state, and
  the second run passes

#### Scenario: A red gate names the §4.4 disposition

- **WHEN** the gate fails on a state-asserting schema
- **THEN** the failure states the disposition — the emit converts to a command through the
  ledger's write path; only a name-collision false positive may be suppressed, with justification
  — and points to the documented producer-policy procedure

### Requirement: Suppressions are justified false positives, never exemptions

The gate SHALL support a suppression list for adjudicated name-collision false positives only.
Every suppression entry SHALL carry the finding it suppresses and a written justification; an
entry missing its justification SHALL fail the gate, and an entry matching no current finding
(stale) SHALL fail the gate naming the dead entry. A suppression SHALL affect exactly the finding
it names — a genuinely state-asserting producer is never suppressed; it converts to an ingress
adapter per §4.4, with no grandfathering.

#### Scenario: A justified suppression suppresses exactly the named finding

- **WHEN** the suppression list carries a justified entry for one adjudicated false-positive
  finding and the gate runs over a tree producing that finding and a second, unrelated finding
- **THEN** the named finding is suppressed and the gate still fails on the unrelated finding

#### Scenario: A stale or unjustified suppression fails the gate

- **WHEN** the suppression list carries an entry with no justification, or an entry that matches
  no finding the current tree produces
- **THEN** the gate fails naming the offending entry
