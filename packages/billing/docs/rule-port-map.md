# Billing rule-port map

Task 1.2 (connector-pattern). For each dbt model and test under
`data-platform/management/models/billing/verdict/` and `data-platform/management/tests/billing/`,
this names its pulse counterpart in `packages/billing`, or flags it `stays-mart-side` with the
missing fact (design.md risk 5).

## Source snapshot

The pinned path (`management/models/billing/verdict/`) is **not committed anywhere in
`data-platform`** — not on `origin/main`, not on any remote branch. It exists only as two
uncommitted files in a local checkout on branch `dna-1136-spike-mongo-cdc-risingwave-snowflake`,
by design's own admission a spike ("*spike pins one code; widen after Gate E*",
`verdict_billing_episode.sql`). This map is pinned to that local snapshot per explicit direction
(the alternative — treating `data-platform`'s committed rule tree as the source — was rejected
by that instruction). `management/tests/billing/` on that same local branch differs from
`origin/main`'s committed copy by two files: it is missing
`assert_seed_offplatform_minutes_counted.sql` and `assert_seed_offplatform_no_double_count.sql`
(present on `origin/main`, absent locally) and adds
`assert_verdict_append_on_change.sql` / `assert_verdict_indeterminate_has_reason.sql` (present
locally, not on `origin/main` — written against the new spike model). The 70 local test files are
the pinned test list; the repo test (`tests/test_rule_port_map.py`) pins this exact set.

**Before this map is acted on**, the spike files need to actually land as a commit in
`data-platform` (they don't exist as shared source today) — that is outside this task's scope
but is a prerequisite for task 3.3 to have something durable to port from.

## Target verdict type

The spike's own verdict-type names (`billing_cpt_achieved.99454`, `billing_episode_qualified`)
are **not** the registered vocabulary the shipped relay accepts —
`packages/verdict-relay/src/verdict_relay/config.py`'s `SUBJECT_TYPE_BY_VERDICT` registers only
`billing_eligibility` → `billing_episode`, `coverage_eligibility` → `coverage`,
`benefits_verification` → `coverage`; an unregistered type fails row validation before any API
call. `billing_episode_qualified` is the semantic match for `billing_eligibility` (both mean
"is this billing episode qualified", the episode-level rollup); `billing_cpt_achieved.99454` has
no registered counterpart — it is spike-internal, one input into the episode rollup, not a type
pulse ever declares on its own. Every row below targets `billing_eligibility` (there is no
`coverage_eligibility` / `benefits_verification` dbt source in this pinned scope — those two
registered types have no counterpart here at all, not a gap, just outside what this tree
computes). Module path for all "ported" rows:
`packages/billing/src/billing/rules/billing_eligibility.py`,
`RULE_VERSION = "pulse-billing-eligibility-v1"` (design.md decision 4).

## Ledger fact surface used to judge portability

A dbt test's underlying fact counts as portable only if it reduces to a state or command field
`catalog/state_catalog.yaml` already declares: `consent` (`granted`/`revoked`/…), `device`
(`active`, …), `enrollment` (`active`/`on_hold`/…), `billing_episode` (opened with a `month`),
`coverage`. Per `design/migration/rpc-object-model-assessment.md` I8, "device readings are
warehouse-only Observations" — raw telemetry (reading counts, monitoring minutes, notes, review
counts, clinic-level program-enablement flags, care-plan approval, EMR order dates) is not in the
catalog and has no committed plan to enter it. Every test whose assertion bottoms out in one of
those raw facts is `stays-mart-side`, named per test; nothing here invents a new event type.

## Models

| dbt object | pulse counterpart | status |
|---|---|---|
| `verdict_billing_episode` | Outcome/reason classification shape (given `achieved: bool`, `period_end`, `as_of` → `positive`/`negative`/`indeterminate` + reason) ports to `billing_eligibility.classify_outcome` — pure, no warehouse read. | **split**: shape ported; see below |
| ↳ same model, `achieved` input | The `achieved` flag this model consumes is computed upstream (`billing_result_detailed`, outside this pinned path) from per-code telemetry thresholds. | **stays-mart-side** — missing fact: per-(subject, cpt-code) `achieved` boolean; source is data-platform's `billing_result_detailed` rollup over device/monitoring telemetry, not a pulse ledger event |
| `verdict_run_audit` | No per-subject verdict semantic — it's a latency instrument (source recency across Mongo `persona_activities`/`monitoring_time_raw`/`persona_notes` vs run time). The engine's own consume-loop watermark + receipt counts (`pulse_core.connector`, task 2.2/3.4) is its architectural replacement, not a port of this model. | **stays-mart-side** — missing fact: source-table recency (`created_at`/`updated_at`) on raw Mongo billing collections; pulse's engine has no equivalent because it never reads those collections |

## Verdict shape / mart mechanics (portable — 2 tests)

| dbt test | pulse counterpart | status |
|---|---|---|
| `assert_verdict_indeterminate_has_reason` | Already implemented: `pulse_core.catalog_gen`'s generated `_require_reason_when_<verdict_field>_indeterminate` validator (mandatory-reason-on-indeterminate, I3) — exercised in `packages/pulse-core/tests/test_generated_catalog.py`. No new code; this test's rule already has a pulse home. | **ported (existing)** |
| `assert_verdict_append_on_change` | The engine never writes an unchanged (outcome, reason) pair twice — this is the billing-engine spec's own "Re-evaluating unchanged facts declares nothing new" scenario, carried by `pulse_core.connector`'s declare-pipeline idempotency (task 2.2) inside `billing.engine.evaluate_and_declare` (task 3.4). Unit test: `packages/billing/tests/test_engine.py::test_unchanged_facts_declare_nothing_new`. | **ported (task 3.4)** |

## Consent gating (portable — 4 tests)

Consent (`consent.granted`) and the episode's own `month` (from `open_billing_episode`) are both
ledger-native, so the boundary comparison — does consent precede the episode's period end — is a
pure function over facts the engine already has, independent of which code was achieved.

| dbt test | pulse counterpart | status |
|---|---|---|
| `assert_consent_gates_achievement` | `billing_eligibility.gate_by_consent(achieved, consent_start, period_end)` — unit test `test_billing_eligibility.py::test_consent_start_after_period_end_gates_false` | **ported** |
| `assert_consent_after_period_not_achieved` | same function — `test_billing_eligibility.py::test_late_consent_not_achieved` | **ported** |
| `assert_consent_before_period_achieved` | same function — `test_billing_eligibility.py::test_early_consent_achieved` | **ported** |
| `assert_protocol_change_independent` | Gate is portable per-protocol (two independent `gate_by_consent` calls, one per program); the specific codes it asserts achieved (`99454`, `99458`) are not — see the RPM group below. Unit test for the independence property only: `test_billing_eligibility.py::test_gates_evaluate_independently_per_program`. | **split** — gate ported; code-achievement inputs stay-mart-side (see `assert_99454_*`, RPM group) |

## RPM CPT-code thresholds — 99453/99445/99454 (stays-mart-side — 18 tests)

Missing fact: per-day distinct reading-day counts and per-reading source/device-type
classification from device telemetry (bodytrace/withings/foracare/etc.), rolled up per
(user, clinic, period). Not a ledger event (I8); no committed plan to make it one.

| dbt test | status |
|---|---|
| `assert_99445_99454_mutually_exclusive` | **stays-mart-side** |
| `assert_99445_threshold_range_consistency` | **stays-mart-side** |
| `assert_99453_achievement_matches_threshold` | **stays-mart-side** |
| `assert_99453_only_period_1` | **stays-mart-side** |
| `assert_99454_achievement_matches_threshold` | **stays-mart-side** |
| `assert_99454_sources_are_eligible` | **stays-mart-side** |
| `assert_device_always_achieved` | **stays-mart-side** |
| `assert_day_count_matches_day_activity` | **stays-mart-side** — pipeline-integrity check on the same telemetry rollup |
| `assert_seed_99445_1_day_not_achieved` | **stays-mart-side** |
| `assert_seed_99445_15_days_achieved` | **stays-mart-side** |
| `assert_seed_99445_2_days_achieved` | **stays-mart-side** |
| `assert_seed_99453_period_1_achieved` | **stays-mart-side** |
| `assert_seed_99453_period_2_not_present` | **stays-mart-side** |
| `assert_seed_99454_15_days_not_achieved` | **stays-mart-side** |
| `assert_seed_99454_16_days_achieved` | **stays-mart-side** |
| `assert_seed_99454_ineligible_source_excluded` | **stays-mart-side** |
| `assert_seed_99454_manual_entry_achieved` | **stays-mart-side** |
| `assert_seed_99454_mixed_sources` | **stays-mart-side** |

## CGM — 95251 (stays-mart-side — 6 tests)

Missing fact: monthly libre/dexcom reading counts and `cgm_analysis` note existence — both
sourced from Mongo `monitoring_time_raw` / `persona_notes`, not a ledger event.

| dbt test | status |
|---|---|
| `assert_95251_achievement_matches_threshold` | **stays-mart-side** |
| `assert_95251_achievement_requires_note` | **stays-mart-side** |
| `assert_95251_sources_are_eligible` | **stays-mart-side** |
| `assert_seed_95251_below_threshold_not_achieved` | **stays-mart-side** |
| `assert_seed_95251_dexcom_achieved` | **stays-mart-side** |
| `assert_seed_95251_no_note_not_achieved` | **stays-mart-side** |

## PCM/CCM classification and monitoring tiers (stays-mart-side — 9 tests)

Missing fact: active-condition count, care-plan review count, care-plan update flag, and
per-tier monitoring-minute sums — all EHR/Mongo-sourced, not a ledger event.

| dbt test | status |
|---|---|
| `assert_pcm_ccm_classification_ccm_complex` | **stays-mart-side** |
| `assert_pcm_ccm_classification_ccm_non_complex` | **stays-mart-side** |
| `assert_pcm_ccm_classification_pcm` | **stays-mart-side** |
| `assert_pcm_ccm_insufficient_reviews_excluded` | **stays-mart-side** |
| `assert_pcm_ccm_monitoring_2x_ccm_non_complex` | **stays-mart-side** |
| `assert_pcm_ccm_monitoring_tier2_ccm_complex` | **stays-mart-side** |
| `assert_pcm_ccm_monitoring_tier2_pcm` | **stays-mart-side** |
| `assert_pcm_ccm_review_boundary` | **stays-mart-side** |
| `assert_compound_monitoring_group` | **stays-mart-side** — cross-program (RPM+CCM) grouping, same missing facts |

## Monitoring-minute aggregation and code selection (stays-mart-side — 8 tests)

Missing fact: raw monitoring-session start/end timestamps per provider, and their
deduplication/merge across overlapping sessions — Mongo `monitoring_time_raw`, not a ledger
event.

| dbt test | status |
|---|---|
| `assert_monitoring_below_threshold_no_codes` | **stays-mart-side** |
| `assert_monitoring_codes_in_allowed_set` | **stays-mart-side** |
| `assert_monitoring_deduplication_no_double_count` | **stays-mart-side** |
| `assert_monitoring_excludes_pre_activation` | **stays-mart-side** — also needs `device_activation_date`, which is ledger-native (`device.active`), but the monitoring-seconds side is not, so the comparison as a whole stays mart-side |
| `assert_monitoring_intermediate_threshold` | **stays-mart-side** |
| `assert_monitoring_multi_provider_aggregates` | **stays-mart-side** |
| `assert_optimal_code_selection` | **stays-mart-side** — reimbursement-based code selection additionally touches rate/reimbursement data, which `billing-boundary.md` bars from ever entering pulse regardless of fact-sourcing |
| `assert_no_duplicate_billing_results` | **stays-mart-side** — pipeline-integrity check on the same upstream rollup |

## APCM — G0556 (stays-mart-side — 6 tests)

Missing fact: approved-care-plan status, monitoring-minutes > 0, and enrollment-status detail
beyond the ledger's coarse `enrollment` states — EHR/Mongo-sourced.

| dbt test | status |
|---|---|
| `assert_seed_apcm_no_careplan_excluded` | **stays-mart-side** |
| `assert_seed_apcm_no_monitoring_excluded` | **stays-mart-side** |
| `assert_seed_apcm_not_enrolled_excluded` | **stays-mart-side** |
| `assert_seed_apcm_only_achieved` | **stays-mart-side** |
| `assert_seed_apcm_pcm_mutual_exclusivity` | **stays-mart-side** |
| `assert_seed_apcm_rpm_stackable` | **stays-mart-side** |

## Program-membership / clinic config (stays-mart-side — 6 tests)

Missing fact: clinic-level program-enablement flags (`rpm_enabled`, `pcm_ccm_enabled`) — not
present in `catalog/state_catalog.yaml` or any pulse event catalog; today only knowable from
data-platform's clinic dimension. (`device_activation_date` and consent are ledger-native, but
the clinic flag these tests also gate on is not, so the composite gate stays mart-side rather
than being split further.)

| dbt test | status |
|---|---|
| `assert_billing_type_values` | **stays-mart-side** |
| `assert_seed_dual_eligible_both_types` | **stays-mart-side** |
| `assert_seed_rpm_eligible` | **stays-mart-side** |
| `assert_seed_rpm_no_consent_not_eligible` | **stays-mart-side** |
| `assert_seed_rpm_clinic_disabled_not_eligible` | **stays-mart-side** |
| `assert_seed_pcm_eligible` | **stays-mart-side** |

## Period/pipeline framing (stays-mart-side / superseded — 7 tests)

Pulse's `billing_episode` opens with a `month` (`open_billing_episode.month`, ledger-native) —
a calendar-month grain, not the dbt pipeline's rolling 30-day window anchored on "first billable
reading after an education note." The structural invariants below are internal-consistency
checks on *that* dbt-computed window; they have no pulse counterpart to violate because the
engine never builds that window. Flagged stays-mart-side rather than "N/A" because the
underlying anchor fact (first billable reading date, education-note existence) is still
warehouse-only if a future decision ever needs the dbt window's semantics reproduced.

| dbt test | status |
|---|---|
| `assert_period_dates_are_30_day_windows` | **stays-mart-side / superseded** |
| `assert_period_end_after_period_start` | **stays-mart-side / superseded** |
| `assert_period_no_gaps_between_consecutive` | **stays-mart-side / superseded** |
| `assert_period_no_overlaps` | **stays-mart-side / superseded** |
| `assert_seed_period_multi_generation` | **stays-mart-side / superseded** |
| `assert_seed_period_new_patient_start_date` | **stays-mart-side / superseded** |
| `assert_seed_period_no_education_excluded` | **stays-mart-side / superseded** |

## Provider/clinic/patient lifecycle edge cases (stays-mart-side — 3 tests)

Missing fact: raw activity timestamps attributed to a specific clinic after a provider or
patient removal event, and the dbt model's own primary-clinic-only attribution (which its
comments note is itself an incomplete model — "cross-clinic billing per period is not currently
supported"). Not a ledger event either way.

| dbt test | status |
|---|---|
| `assert_provider_change_attribution` | **stays-mart-side** |
| `assert_recent_provider_change` | **stays-mart-side** |
| `assert_removed_patient_activities` | **stays-mart-side** |

## EMR order gating (stays-mart-side — 1 test)

Missing fact: EMR order date and per-clinic `require_emr_order` config — EHR-sourced, not a
ledger event.

| dbt test | status |
|---|---|
| `assert_seed_emr_activity_before_order_excluded` | **stays-mart-side** |

## Coverage of the pinned list

72 pinned objects total: 2 models + 70 tests.

- **Ported or split** (6): `verdict_billing_episode` (split), `assert_verdict_indeterminate_has_reason`,
  `assert_verdict_append_on_change`, `assert_consent_gates_achievement`,
  `assert_consent_after_period_not_achieved`, `assert_consent_before_period_achieved`,
  `assert_protocol_change_independent` (split) — 7 rows carry a ported half; 2 are pure ports,
  2 are split rows whose non-ported half is separately counted below.
- **Stays-mart-side** (65 rows, including `verdict_run_audit` and the non-ported half of each
  split row): every row in the RPM (18), CGM (6), PCM/CCM (9), monitoring (8), APCM (6), program
  membership (6), period framing (7), provider/clinic (3), and EMR (1) groups.

`tests/test_rule_port_map.py` parses this file's tables and asserts the exact pinned 72-object
list (2 models + the 70 local `tests/billing/*.sql` filenames as of this snapshot) each appear
exactly once across the tables above.
