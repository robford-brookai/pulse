# Proposal: billing-state

## Why

Patient billing state is computed continuously — in Snowflake dbt marts, from usage, monitoring,
interactions, and code-completion requirements like consent — and none of it reaches the ledger.
Three facts make the gap concrete:

- **A declared verdict moves no state.** `DeclareVerdictCommand` carries `outcome`, not
  `to_state`; the fold only folds `to_state`-bearing events; `pulse_ledger` has no
  `declare_verdict` handling anywhere. Even if the mart's billing verdicts were declared today,
  `billing_episode` would never leave `open`. The "derived-then-declared" invariant (I3) is
  specified but not closed.
- **The relay has no production trigger.** `verdict_relay.run` documents its own deferral:
  production wiring (Snowflake `RowSource`, cursor store, service client from configuration)
  "arrives with the scheduler trigger (S1.3); until then callers construct". Nothing runs it.
- **Coverage has no home.** The object model designs Coverage (patient × payer, QMB, the
  Eligibility → BenefitsVerification verdict chain) but the catalog has no coverage subject —
  no `current_state` row to enumerate, no transition events to broadcast.

The consequence: the ledger, the bus, and every consumer are blind to whether a patient is
billable this cycle and whether their coverage is verified — the two facts the business needs
continuously.

## What Changes

- **Outcome→transition pairing in the relay (the missing fold).** For configured verdict types,
  the declarer follows a committed or replayed `declare_verdict` with a D16-idempotent
  `declare_transition` on the same subject, mapped from the outcome via per-verdict-type
  configuration (`transition_by_outcome`). Rejected transitions (e.g. an episode already
  `reported`) are counted distinctly and never retried — at `reported`, rejection is the correct
  terminal answer.
- **New verdict types on the existing mart contract.** `billing_eligibility` (→
  `billing_episode`: positive → `qualified`, negative → `not_qualified`) and
  `coverage_eligibility` / `benefits_verification` (→ `coverage`). The pinned eight-column mart
  contract is deliberately unchanged — new types are new `verdict_type` values.
- **`coverage` as a catalog subject (recommended; design.md carries the alternative).** Patient ×
  payer grain, coarse states (`unverified → verified_active ⇄ verified_inactive → lapsed`,
  terminal `terminated`), MINOR catalog bump 1.0.0 → 1.1.0, plus the Alembic migration widening
  the three subject-type CHECK constraints — the gap
  `test_communication_consent_validates_but_cannot_yet_be_committed` already proves.
- **Production wiring + poll trigger for the relay.** Config-constructed Snowflake `RowSource`,
  cursor store, and service client; `task relay:run TARGET=<env>` (credentialed, out of
  `task check`); a scheduled poll on `computed_at` in the schedules package. An extra run is a
  guaranteed no-op (D16 + cursor + stale-skip), so polling approximates "after every dbt
  refresh" without a cross-repo trigger.
- **Broadcast rides the existing pipe.** Ledger events already publish on the `patient-state`
  bus domain; the change makes the billing events exist, not the transport. No new domain, no
  Terraform.

## Capabilities

- `coverage-state` (new) — the coverage subject: grain, state machine, record admission
  (CHECK-constraint widening), first-declare rule, no-PHI posture for payer identifiers.
- `verdict-relay-trigger` (new) — production wiring, the credentialed run target, poll cadence,
  no-op-run semantics.
- `verdict-declare` (modified) — the outcome→transition pairing requirements.
- `verdict-relay-run` (modified) — the receipt gains transition counts.

## Out of scope

- **Claims lifecycle** (D6 stands: the episode lifecycle stops at `reported`; `billed →
  reconciled` and claim-outcome ingestion stay reserved behind config).
- **A Billy connector** (BF-0c stays blocked). Billy's manual benefits-verification verdicts are
  distinguished by `rule_version` whenever they reach the mart; how they reach it is an open
  question below.
- **A Twenty-native billing object.** Rejected as a store: Twenty is a projection surface, and
  a Twenty object writing "indirectly" into the ledger would be a second write path (ADR-0003
  forbids it; producer policy enforces it). A read-only projected billing status field on the
  board is a natural follow-up to `twenty-projection`, not part of this change.
- **A new bus domain.** `patient-state` carries the events; consumers filter on `event_type`.

## Entry conditions

`twenty-projection` is in flight and owns three serial lanes this change also needs. Tasks in
this change touching those lanes are sequenced behind it (or behind explicit lane handoff):

- `catalog_generated_surfaces` — `catalog/state_catalog.yaml`, `pulse_core.generated`, artifact
  regeneration (this change's task 1.1).
- `workspace_roots` — root `Taskfile.yml` (this change's task 3.1).
- `openspec_main_specs` — `docs/contracts/publishes.md` + root `mkdocs.yml` nav (this change's
  task 3.2).

## Open questions (decided in review or flagged to their owners, never silently)

1. **Coverage modeling A vs B** — new subject (recommended) vs verdicts-only; design.md carries
   both. Decide at proposal review.
2. **dbt mart seam ownership** — who adds the `billing_eligibility` / `coverage_eligibility` /
   `benefits_verification` rows to the mart, and does the dbt repo adopt a `publishes.md` pin?
   Blocks wave 3 only. **Decided 2026-08-26 (DNA-1252):** the streamline dbt project owns the
   mart (`STREAMLINE.OCEAN_MARTS.OCEAN_VERDICTS`, `Brookai/streamline#20`) with a `publishes.md`
   pin in that repo; v1 rows come from a manually adjudicated seed (the question-4 "Billy manual
   runner" posture, `rule_version manual-*-v1`), rules-engine SQL later behind the same contract.
3. **pricing-engine's seam** — the Brook `pricing-engine` app connects to pulse via a connector.
   Does it feed the Snowflake mart (verdict-relay declares on its behalf), or declare directly
   through the command API under its own credential (`customerio-consent-ingress` precedent)?
   Either fits the architecture; a Twenty-native store does not (see Out of scope).
4. **Billy manual-verdict entry path** — mart rows now, or out of v1 with `rule_version`
   reserving the seam for the future 270/271 automation.
5. **Coverage grain and vocabulary** — patient × payer vs patient × coverage-instance; the
   exact state set; QMB and benefit-category detail live in verdict payload/lineage, never in
   the state vocabulary (recommended). Needs billing-team confirmation.
6. **subject_id addressing** — confirmation that the mart can address `billing_episode`
   subject ids via `warehouse-event-sync`, and the coverage first-declare rule.
   **Decided 2026-08-26:** confirmed — the mart joins `billing_eligibility` rows to
   `STG_EVENTS.EVENTS` subjects; the coverage subject-key convention is now pinned in the
   coverage-state delta (`{patient_subject_key}:{sha256(payer)[:16]}`).
7. **Cadence SLO** — poll interval; whether the 26 h verdict-staleness monitor tightens for
   billing verdict types.
8. **Exclusivity interaction** — whether `qualified → not_qualified` mid-month re-opens the
   patient's exclusivity-group slot for a sibling program.
