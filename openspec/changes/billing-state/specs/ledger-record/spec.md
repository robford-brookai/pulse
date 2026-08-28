## Purpose

Registration commands that open a state-machine subject must actually set its entry state —
discovered live on dev (DNA-1261): `open_billing_episode` committed its event non-state-bearing,
so an opened episode had no `current_state` row and the verdict-relay's paired first transition
was rejected as a genesis violation.

## ADDED Requirements

### Requirement: A registration command lands state-bearing at its subject's entry state

A command whose meaning is "this subject now exists in its entry state" — today exactly
`open_billing_episode`, whose catalog shape carries no `to_state` field — SHALL commit as a
state-bearing genesis event at the subject's derived initial state: the server supplies the
implied `to_state` from an explicit per-command mapping derived from the catalog's adjacency,
the event joins the fold, and `current_state` gains the subject at its entry state in the same
transaction. The mapping SHALL be explicit and per-command, never a blanket rule over commands
lacking `to_state`: registry subjects (`mint_person` — no state machine) stay non-state-bearing
by design, and implied-transition commands (`resolve_referral` → `resolved`) are a different
semantic owned by their own change.

#### Scenario: An opened episode exists in current_state at `open`

- **GIVEN** an `open_billing_episode` command for an enrollment × month the ledger has not seen
- **WHEN** it commits
- **THEN** the event is state-bearing at `open`, `current_state` holds the episode at `open`,
  and a subsequent `declare_transition` to `qualified` validates as departing from `open`

#### Scenario: A wire body that already carries to_state is untouched

- **GIVEN** a declaration whose body carries an explicit `to_state`
- **WHEN** it is coerced at the wire boundary
- **THEN** the implied-state mapping is not consulted — an explicit `to_state` always wins
