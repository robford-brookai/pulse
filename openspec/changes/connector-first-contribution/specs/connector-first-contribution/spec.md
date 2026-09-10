## Purpose

Proves that a contributor can install, generate both connector directions and make a first commit with the real repository hooks without undocumented repairs.

## ADDED Requirements

### Requirement: Documented setup supports the first real commit

An isolated fresh clone SHALL complete documented install, green task check, inbound and outbound connector generation, documented dependency sync, green task check and an actual first git commit with production hooks enabled. The journey SHALL require no live credentials, hook bypasses, disabled drift checks, staged-file exclusions or manual package-count edits. Both connector directions SHALL coexist.

#### Scenario: Both connector directions reach first commit

- **GIVEN** an isolated fresh clone with fixture git identity and the published setup guide
- **WHEN** the contributor installs, checks, generates both connector directions, syncs dependencies, checks and commits
- **THEN** the real commit succeeds with production hooks enabled and no undocumented intervention or live credential

### Requirement: Setup and green checks preserve intentional changes only

The documented install SHALL initialize the existing OpenLore prerequisite. Package/doc expectations SHALL follow the actual workspace rather than a fixed package count. Successful checks SHALL leave no unrelated tracked-file modifications; runtime timings SHALL be untracked while historical audit rows remain preserved. Each demonstrated in-scope failure SHALL gain a regression case.

#### Scenario: Fresh install initializes hook prerequisite

- **GIVEN** a fresh clone lacking initialized OpenLore state
- **WHEN** the documented installation and first production-hook commit run
- **THEN** OpenLore is initialized through the supported path and the hook succeeds without manual repair or bypass

#### Scenario: Generated packages pass adaptive gates

- **GIVEN** a workspace extended by both generated connector packages
- **WHEN** package and documentation checks evaluate that workspace
- **THEN** the expected workspace contents are validated without editing fixed counts

#### Scenario: Green checks do not dirty timing history

- **GIVEN** a clone containing only intended generated-connector edits and historical audit rows
- **WHEN** the successful quality gate runs
- **THEN** no unrelated tracked changes are produced and historical audit rows remain intact

### Requirement: Fix ownership and scope remain bounded

Template-owned defect corrections SHALL land in rob-ade and be imported through the existing template sync mechanism, with the upstream PR/commit receipt available before dependent sync dispatch. PULSE-specific gates SHALL be corrected in PULSE. Scope SHALL remain the demonstrated OpenLore setup, fixed package/doc expectation and tracked timing-output defect families. Unrelated new findings SHALL receive separate proposals. The 42 previously closed findings and frozen audit history SHALL remain credited without restarting devex-eight.

#### Scenario: Template repair follows upstream ownership

- **GIVEN** a reproduced in-scope defect originates in rob-ade
- **WHEN** its PULSE repair is planned and imported
- **THEN** the upstream focused PR/commit receipt precedes template sync and no downstream fork or frozen audit rewrite is used

### Requirement: One independent walkthrough closes contribution acceptance

After the automated journey passes, one engineer other than its implementer SHALL follow the guide in a fresh environment and record commands, outcomes, interventions and diagnostic timing/tool context. Completion SHALL require both connector directions and the first real commit without undocumented repairs or unrelated tracked changes. Missing participant evidence SHALL remain pending; a failed in-scope segment SHALL be reproduced, fixed and rerun without another broad audit wave or score target.

#### Scenario: Independent walkthrough supplies outcome evidence

- **GIVEN** the automated journey passes and an independent engineer is available
- **WHEN** the engineer follows the same guide in a fresh environment
- **THEN** the receipt records actual commands and outcomes for both directions and first commit, with no undocumented interventions or unrelated tracked changes

#### Scenario: Acceptance does not fabricate or restart audits

- **GIVEN** an independent participant is unavailable or a bounded segment fails
- **WHEN** acceptance status is recorded
- **THEN** missing evidence remains pending or only the concrete failed in-scope segment is repaired and rerun; no new score audit is opened
