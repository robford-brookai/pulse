# end-to-end-demo Specification

## Purpose
One runnable demonstration that walks a single synthetic patient through every seam Pulse
owns, in order, and stops with a failure the moment any promise the four earlier demos made
stops holding when the seams are chained.
## Requirements
### Requirement: One patient crosses every seam in order
The demo SHALL drive one synthetic patient, generated deterministically from the pinned
synthetic population, through six stages in a fixed order: identity resolution of a referral,
consent ingress from an export landing row, a signed board drag, a verdict declared from the
mart read, agreement of every window with the ledger, and a projection rebuild from the
journal. Each stage SHALL assert its outcome against the ledger before the next stage begins.

#### Scenario: A legal path reaches the end
- **WHEN** the demo runs against a fresh stack with the pinned cohort
- **THEN** every stage passes in order and the process exits zero with a receipt naming each
  stage, its assertion count, and the subject keys it touched

#### Scenario: A broken seam stops the walk
- **WHEN** any stage's assertion fails
- **THEN** the demo stops at that stage, prints which assertion failed and which stage owns
  it, and exits nonzero without running later stages

### Requirement: Every door is exercised the way its producer uses it
Each stage SHALL enter the ledger through the same surface its real producer uses: the
identity matcher's resolution path, the consent sweep against a landing table, the signed
webhook route for the drag, the relay's declare pipeline for the verdict. No stage SHALL write
ledger tables directly.

#### Scenario: Identity resolves three ways
- **WHEN** the cohort's three referral variants arrive
- **THEN** the first mints a new patient, the second matches exactly by identifier, and the
  third is quarantined for a human, with no guessed merge

#### Scenario: Consent lands attributed
- **WHEN** the fixture consent export row is swept
- **THEN** the ledger records the consent state with the messaging platform as its actor and a
  second sweep of the same row changes nothing

#### Scenario: The board is a door with a lock
- **WHEN** a correctly signed legal drag and then an illegal drag arrive for the patient's card
- **THEN** the legal drag commits one event, the illegal drag is rejected with the catalog's
  reason, exactly one explanatory note reaches the card, and a tampered signature is refused
  before any rule runs

#### Scenario: A verdict becomes state
- **WHEN** the fixture mart row for the patient's episode is relayed
- **THEN** the verdict event and its paired transition commit, the coverage subject is minted
  on first sight, and an immediate rerun declares nothing new

### Requirement: Every window agrees with the ledger
After the producing stages, the demo SHALL compare each read surface to the ledger's
`current_state` for the patient's subjects and SHALL fail on any disagreement.

#### Scenario: Board, warehouse copy, and fold agree
- **WHEN** the producing stages have completed
- **THEN** the board projection's rows, the warehouse landing's events for those subjects, and
  an independent fold of the journal each equal the ledger's current state for every subject
  the patient touched

### Requirement: Two modes, one assertion set
The demo SHALL run offline against the local event stack with fixture landing tables and an
in-process board route, and SHALL run live against the development ledger, board, and
warehouse landing when invoked with a live flag. The assertions SHALL be identical in both
modes; only the transports differ.

#### Scenario: Offline needs no credential
- **WHEN** the demo runs without the live flag
- **THEN** it completes with no network beyond the local stack and no credential value in the
  environment, and it is invocable from a single task target

#### Scenario: Live leaves a receipt
- **WHEN** the demo runs with the live flag in an attended session
- **THEN** it writes only to the development ledger and board, reads the warehouse landing
  read-only, and emits a receipt of counts and subject keys suitable for a tracking issue

### Requirement: Synthetic only, and nothing sensitive leaves the process
All demo data SHALL come from the pinned synthetic population and committed fixtures. No log
line, receipt, or assertion message SHALL contain a payload value, a credential value, or
anything resembling protected health information.

#### Scenario: A failure message names position, not content
- **WHEN** an assertion fails on a row or event
- **THEN** the message names the stage, the subject key, and the field, never the field's value

### Requirement: The demo stays out of the check gate but stays importable
The demo SHALL be excluded from the check gate because it needs the local stack, and a
smoke-parse test SHALL keep it importable and its argument parser valid under the check gate.

#### Scenario: Check passes without a stack
- **WHEN** the check gate runs on a machine with no local stack
- **THEN** the smoke-parse test passes and no demo stage executes

