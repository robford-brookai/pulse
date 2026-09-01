"""The rule-port-map coverage test (connector-pattern 1.2).

Pins the exact set of dbt objects the mapping document must name — the two models under
`data-platform/management/models/billing/verdict/` plus the 70 test files under
`data-platform/management/tests/billing/`, as they exist on the pinned local snapshot named in
`packages/billing/docs/rule-port-map.md` ("Source snapshot"). `data-platform` is a separate repo
not available to this repo's CI, so the pinned list is a hardcoded snapshot, not a live read —
same pattern as `test_producer_registry.py`'s hardcoded `EXPECTED_COLUMNS`.

Every pinned object must appear in the map's tables exactly once: a dbt object present zero times
is an omission (a silent verdict gap per the task's own framing); present more than once means
the map disagrees with itself about what ported it.

Offline, no network, no credentials — reads only the committed doc.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = REPO_ROOT / "packages" / "billing" / "docs" / "rule-port-map.md"

#: The 2 dbt models pinned by the task, as they exist on the local spike snapshot
#: (`management/models/billing/verdict/`) — see the map's "Source snapshot" section.
PINNED_MODELS = (
    "verdict_billing_episode",
    "verdict_run_audit",
)

#: The 70 dbt test files pinned by the task (`management/tests/billing/*.sql`), as they exist on
#: that same local snapshot — two files present on `data-platform`'s `origin/main`
#: (`assert_seed_offplatform_minutes_counted`, `assert_seed_offplatform_no_double_count`) are
#: absent from the snapshot and so are not pinned; two files present on the snapshot
#: (`assert_verdict_append_on_change`, `assert_verdict_indeterminate_has_reason`) are not on
#: `origin/main` and are pinned because they exist today, against the new spike model.
PINNED_TESTS = (
    "assert_95251_achievement_matches_threshold",
    "assert_95251_achievement_requires_note",
    "assert_95251_sources_are_eligible",
    "assert_99445_99454_mutually_exclusive",
    "assert_99445_threshold_range_consistency",
    "assert_99453_achievement_matches_threshold",
    "assert_99453_only_period_1",
    "assert_99454_achievement_matches_threshold",
    "assert_99454_sources_are_eligible",
    "assert_billing_type_values",
    "assert_compound_monitoring_group",
    "assert_consent_after_period_not_achieved",
    "assert_consent_before_period_achieved",
    "assert_consent_gates_achievement",
    "assert_day_count_matches_day_activity",
    "assert_device_always_achieved",
    "assert_monitoring_below_threshold_no_codes",
    "assert_monitoring_codes_in_allowed_set",
    "assert_monitoring_deduplication_no_double_count",
    "assert_monitoring_excludes_pre_activation",
    "assert_monitoring_intermediate_threshold",
    "assert_monitoring_multi_provider_aggregates",
    "assert_no_duplicate_billing_results",
    "assert_optimal_code_selection",
    "assert_pcm_ccm_classification_ccm_complex",
    "assert_pcm_ccm_classification_ccm_non_complex",
    "assert_pcm_ccm_classification_pcm",
    "assert_pcm_ccm_insufficient_reviews_excluded",
    "assert_pcm_ccm_monitoring_2x_ccm_non_complex",
    "assert_pcm_ccm_monitoring_tier2_ccm_complex",
    "assert_pcm_ccm_monitoring_tier2_pcm",
    "assert_pcm_ccm_review_boundary",
    "assert_period_dates_are_30_day_windows",
    "assert_period_end_after_period_start",
    "assert_period_no_gaps_between_consecutive",
    "assert_period_no_overlaps",
    "assert_protocol_change_independent",
    "assert_provider_change_attribution",
    "assert_recent_provider_change",
    "assert_removed_patient_activities",
    "assert_seed_95251_below_threshold_not_achieved",
    "assert_seed_95251_dexcom_achieved",
    "assert_seed_95251_no_note_not_achieved",
    "assert_seed_99445_1_day_not_achieved",
    "assert_seed_99445_15_days_achieved",
    "assert_seed_99445_2_days_achieved",
    "assert_seed_99453_period_1_achieved",
    "assert_seed_99453_period_2_not_present",
    "assert_seed_99454_15_days_not_achieved",
    "assert_seed_99454_16_days_achieved",
    "assert_seed_99454_ineligible_source_excluded",
    "assert_seed_99454_manual_entry_achieved",
    "assert_seed_99454_mixed_sources",
    "assert_seed_apcm_no_careplan_excluded",
    "assert_seed_apcm_no_monitoring_excluded",
    "assert_seed_apcm_not_enrolled_excluded",
    "assert_seed_apcm_only_achieved",
    "assert_seed_apcm_pcm_mutual_exclusivity",
    "assert_seed_apcm_rpm_stackable",
    "assert_seed_dual_eligible_both_types",
    "assert_seed_emr_activity_before_order_excluded",
    "assert_seed_pcm_eligible",
    "assert_seed_period_multi_generation",
    "assert_seed_period_new_patient_start_date",
    "assert_seed_period_no_education_excluded",
    "assert_seed_rpm_clinic_disabled_not_eligible",
    "assert_seed_rpm_eligible",
    "assert_seed_rpm_no_consent_not_eligible",
    "assert_verdict_append_on_change",
    "assert_verdict_indeterminate_has_reason",
)

PINNED_OBJECTS = PINNED_MODELS + PINNED_TESTS

#: A markdown table row whose first cell is exactly one backtick-quoted identifier — the map's
#: convention for naming a dbt object (a row like "| ↳ same model, `achieved` input | ... |"
#: does not match: its first cell is prose, not a bare identifier, so it isn't miscounted as a
#: second object).
OBJECT_ROW = re.compile(r"^\|\s*`([A-Za-z0-9_]+)`\s*\|", re.MULTILINE)


def _map_text() -> str:
    return MAP_PATH.read_text(encoding="utf-8")


def test_map_exists() -> None:
    assert MAP_PATH.exists(), f"{MAP_PATH.relative_to(REPO_ROOT)} is missing"
    assert _map_text().strip(), f"{MAP_PATH.relative_to(REPO_ROOT)} is empty"


def test_every_pinned_object_appears_exactly_once() -> None:
    named = Counter(OBJECT_ROW.findall(_map_text()))

    missing = [obj for obj in PINNED_OBJECTS if named[obj] == 0]
    assert not missing, (
        f"rule-port-map.md omits {missing} — an omission here is a silent verdict gap (connector-pattern task 1.2)"
    )

    duplicated = [obj for obj in PINNED_OBJECTS if named[obj] > 1]
    assert not duplicated, (
        f"rule-port-map.md names {duplicated} more than once — each pinned object gets exactly one row"
    )


def test_map_names_no_object_outside_the_pinned_list() -> None:
    """Self-check: every backtick-identifier table row is one of the 72 pinned objects — a name
    the map introduces that isn't pinned is either a typo or scope creep beyond this task."""
    named = set(OBJECT_ROW.findall(_map_text()))
    extra = named - set(PINNED_OBJECTS)
    assert not extra, f"rule-port-map.md names object(s) outside the pinned list: {extra}"


def test_pinned_list_row_count() -> None:
    """Self-check: the pinned list itself is 2 models + 70 tests, matching the doc's own count."""
    assert len(PINNED_MODELS) == 2
    assert len(PINNED_TESTS) == 70
    assert len(PINNED_OBJECTS) == len(set(PINNED_OBJECTS)) == 72
