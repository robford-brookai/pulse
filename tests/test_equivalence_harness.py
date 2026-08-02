"""Equivalence harness for the EventBridge migration gate (task 8.1, DNA-773).

The harness captures graph tables + ``audit_log`` after a ``call-simulator`` +
``sim-driver`` run, normalizes exactly the values that are wall-clock or
identifier-random *by construction*, and diffs two runs. These tests pin the
normalization discipline, because that is the whole gate:

- Normalize too little and every comparison fails on noise (wall-clock
  timestamps, uuid4s from call-simulator / agent-worker / event-store).
- Normalize too much and the gate proves nothing — sim-driver's deterministic
  IDs (sha256 of the scenario key) and everything derived from them
  (control-plane's uuid5 task IDs) MUST survive verbatim, so a transport that
  corrupts an identifier still fails the gate.

The harness lives at ``packages/ocean/scripts/equivalence_harness.py`` and is
imported here by file path: ocean's services are not importable packages from
the workspace environment, and the workspace test tree is the CI-covered home
for ocean tooling tests (see test_ocean_bus_dependencies.py).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
HARNESS_PATH = REPO_ROOT / "packages" / "ocean" / "scripts" / "equivalence_harness.py"

spec = importlib.util.spec_from_file_location("equivalence_harness", HARNESS_PATH)
assert spec is not None and spec.loader is not None
eh = importlib.util.module_from_spec(spec)
sys.modules["equivalence_harness"] = eh  # dataclasses resolve types via sys.modules
spec.loader.exec_module(eh)


# --- Scenario fixtures (synthetic; mirrors sim-driver scenario yaml shape) ---

SCENARIO = {
    "name": "smoke",
    "patients": [
        {
            "patient_id": "sim-pt-001",
            "clinic_id": "clinic-demo",
            "signals": [
                {"sim_hour": 0.05, "type": "glucose", "value": 225, "anomalous": True},
                {"sim_hour": 0.10, "type": "weight", "value": 70, "anomalous": False},
            ],
        },
    ],
}

# Golden values, computed independently of the harness with the exact
# derivations the services use (sim-driver _deterministic_id, control-plane
# uuid5 task ids, sim-driver bookends).
SIG_ID = "78052dcc-f531-b763-38be-4d61012e23bc"  # sha256("sim:smoke:sim-pt-001:0")[:16]
ALERT_ID = "9821dd7f-d9de-c5a4-76b0-486089497a68"  # sha256("sim:smoke:sim-pt-001:0_alert")[:16]
TASK_ID = "6f0e21c2-4ebf-554e-a11e-635fa51a08bf"  # uuid5(NAMESPACE_URL, "task-<ALERT_ID>")
BOOKEND_STARTED = "5f62cddc-a46d-7033-c5e3-92f8344de734"  # sha256("sim:smoke:scenario.started")[:16]
BOOKEND_COMPLETED = "ed0b87c3-aecd-6953-4b90-760014f7e014"

RANDOM_A = "11111111-2222-4333-8444-555555555555"
RANDOM_B = "99999999-8888-4777-8666-555555555555"


def make_snapshot(interaction_id: str, event_id: str, audit_id: str) -> dict:
    """One simulated run's raw capture, parameterized by its random IDs."""
    return {
        "meta": {"scenario": "smoke", "label": "run"},
        "deterministic_ids": sorted(eh.deterministic_ids(SCENARIO)),
        "tables": {
            "patients": [],
            "signals": [
                {
                    "signal_id": SIG_ID,
                    "patient_id": "sim-pt-001",
                    "signal_type": "glucose",
                    "value": 225.0,
                    "unit": "mg/dL",
                    "received_at": "2026-08-02T10:00:01.123456+00:00",
                    "anomalous": True,
                    "last_event_id": SIG_ID,
                    "last_event_at": "2026-08-02T10:00:01.123456+00:00",
                }
            ],
            "alerts": [
                {
                    "alert_id": ALERT_ID,
                    "patient_id": "sim-pt-001",
                    "alert_type": "glucose_anomaly",
                    "severity": "HIGH",
                    "status": "open",
                    "source_system": "pocar",
                    "created_at": "2026-08-02T10:00:02+00:00",
                    "updated_at": "2026-08-02T10:00:02+00:00",
                    "correlation_id": f"sim-{ALERT_ID}",
                    "last_event_id": ALERT_ID,
                }
            ],
            "tasks": [
                {
                    "task_id": TASK_ID,
                    "alert_id": ALERT_ID,
                    "patient_id": "sim-pt-001",
                    "task_type": "outreach_call",
                    "priority": "HIGH",
                    "status": "open",
                    "assigned_to": None,
                    "created_at": "2026-08-02T10:00:03+00:00",
                    "updated_at": "2026-08-02T10:00:03+00:00",
                    "last_event_id": event_id,
                }
            ],
            "interactions": [
                {
                    "interaction_id": interaction_id,
                    "task_id": TASK_ID,
                    "patient_id": "sim-pt-001",
                    "interaction_type": "call",
                    "outcome": "completed",
                    "started_at": "2026-08-02T10:00:04+00:00",
                    "completed_at": "2026-08-02T10:00:09+00:00",
                    "last_event_at": "2026-08-02T10:00:04+00:00",
                    "last_event_id": event_id,
                }
            ],
            "outcomes": [],
            "tickets": [],
            "ticket_tasks": [],
            "alert_tasks": [],
            "ticket_alerts": [],
            "task_escalation_state": [
                {
                    "id": 7,
                    "entity_type": "task",
                    "entity_id": TASK_ID,
                    "priority_at_creation": "HIGH",
                    "current_priority": "HIGH",
                    "created_at": "2026-08-02T10:00:03+00:00",
                    "last_checked_at": "2026-08-02T10:00:03+00:00",
                    "escalated_at": None,
                    "escalation_count": 0,
                }
            ],
            "audit_log": [
                {
                    "audit_id": audit_id,
                    "event_id": SIG_ID,
                    "action_type": "event.ingested",
                    "actor_id": "system",
                    "source_system": "pocar",
                    "entity_type": "signal",
                    "entity_id": SIG_ID,
                    "timestamp": "2026-08-02T10:00:01.500000+00:00",
                    "detail": {"event_type": "signal.received", "topic": "signals"},
                    "recorded_at": "2026-08-02T10:00:01.600000+00:00",
                }
            ],
        },
    }


def run_a() -> dict:
    return make_snapshot(interaction_id=RANDOM_A, event_id=str(uuid.uuid4()), audit_id=str(uuid.uuid4()))


def run_b() -> dict:
    return make_snapshot(interaction_id=RANDOM_B, event_id=str(uuid.uuid4()), audit_id=str(uuid.uuid4()))


# --- Deterministic-ID universe ---


class TestDeterministicIds:
    def test_contains_signal_alert_task_and_bookend_ids(self):
        ids = eh.deterministic_ids(SCENARIO)
        assert SIG_ID in ids
        assert ALERT_ID in ids
        assert TASK_ID in ids
        assert BOOKEND_STARTED in ids
        assert BOOKEND_COMPLETED in ids

    def test_alert_id_only_for_anomalous_signals(self):
        # Signal idx 1 is not anomalous: its would-be alert id must not be in
        # the universe, or the harness would preserve an id no service can emit.
        absent = eh.deterministic_ids({
            "name": "smoke",
            "patients": [{"patient_id": "sim-pt-001", "signals": [{"anomalous": False}]}],
        })
        assert ALERT_ID not in absent

    def test_second_signal_id_present(self):
        ids = eh.deterministic_ids(SCENARIO)
        sig1 = eh.sim_uuid("sim:smoke:sim-pt-001:1")
        assert sig1 in ids


# --- Normalization ---


class TestNormalization:
    def test_wall_clock_timestamps_normalized_nulls_preserved(self):
        norm = eh.normalize_snapshot(run_a())
        sig = norm["tables"]["signals"][0]
        assert sig["received_at"] == eh.TS_TOKEN
        assert sig["last_event_at"] == eh.TS_TOKEN
        esc = norm["tables"]["task_escalation_state"][0]
        assert esc["escalated_at"] is None

    def test_deterministic_ids_survive_verbatim(self):
        norm = eh.normalize_snapshot(run_a())
        assert norm["tables"]["signals"][0]["signal_id"] == SIG_ID
        assert norm["tables"]["alerts"][0]["alert_id"] == ALERT_ID
        assert norm["tables"]["tasks"][0]["task_id"] == TASK_ID
        assert norm["tables"]["audit_log"][0]["event_id"] == SIG_ID

    def test_random_uuids_renamed_consistently_across_tables(self):
        snap = run_a()
        # The same random event_id appears on tasks and interactions rows.
        norm = eh.normalize_snapshot(snap)
        t = norm["tables"]["tasks"][0]["last_event_id"]
        i = norm["tables"]["interactions"][0]["last_event_id"]
        assert t == i
        assert t.startswith("<uuid-")
        assert norm["tables"]["interactions"][0]["interaction_id"].startswith("<uuid-")

    def test_embedded_uuid_in_correlation_id(self):
        snap = run_a()
        snap["tables"]["alerts"][0]["correlation_id"] = f"sim-{RANDOM_A}"
        norm = eh.normalize_snapshot(snap)
        corr = norm["tables"]["alerts"][0]["correlation_id"]
        assert corr.startswith("sim-<uuid-")
        # Deterministic embedded uuid is preserved.
        snap2 = run_a()
        norm2 = eh.normalize_snapshot(snap2)
        assert norm2["tables"]["alerts"][0]["correlation_id"] == f"sim-{ALERT_ID}"

    def test_non_uuid_identifiers_preserved(self):
        norm = eh.normalize_snapshot(run_a())
        assert norm["tables"]["signals"][0]["patient_id"] == "sim-pt-001"

    def test_preserved_columns_untouched(self):
        norm = eh.normalize_snapshot(run_a())
        alert = norm["tables"]["alerts"][0]
        assert alert["severity"] == "HIGH"
        assert alert["source_system"] == "pocar"
        assert norm["tables"]["signals"][0]["value"] == 225.0

    def test_serial_sequence_columns_dropped(self):
        norm = eh.normalize_snapshot(run_a())
        assert "id" not in norm["tables"]["task_escalation_state"][0]

    def test_json_detail_timestamps_normalized_topic_preserved(self):
        snap = run_a()
        snap["tables"]["audit_log"][0]["detail"] = {
            "event_type": "signal.received",
            "topic": "signals",
            "seen_at": "2026-08-02T10:00:01+00:00",
        }
        norm = eh.normalize_snapshot(snap)
        detail = norm["tables"]["audit_log"][0]["detail"]
        assert detail["seen_at"] == eh.TS_TOKEN
        # topic is transport-revealing but genuinely stored state: NOT
        # normalized by default. 8.2 must exclude it explicitly and visibly.
        assert detail["topic"] == "signals"

    def test_json_detail_random_uuid_renamed(self):
        snap = run_a()
        snap["tables"]["audit_log"][0]["detail"] = {"ref": RANDOM_A, "det": SIG_ID}
        norm = eh.normalize_snapshot(snap)
        detail = norm["tables"]["audit_log"][0]["detail"]
        assert detail["ref"].startswith("<uuid-")
        assert detail["det"] == SIG_ID

    def test_unknown_column_raises(self):
        snap = run_a()
        snap["tables"]["signals"][0]["surprise_column"] = "x"
        with pytest.raises(eh.UnclassifiedColumnError, match=r"signals\.surprise_column"):
            eh.normalize_snapshot(snap)

    def test_unknown_table_raises(self):
        snap = run_a()
        snap["tables"]["mystery"] = [{"a": 1}]
        with pytest.raises(eh.UnclassifiedColumnError, match="mystery"):
            eh.normalize_snapshot(snap)

    def test_stats_report_preserved_and_renamed_counts(self):
        norm = eh.normalize_snapshot(run_a())
        stats = norm["meta"]["normalization_stats"]
        assert stats["renamed_uuids"] >= 3  # interaction_id, event_id, audit_id
        assert stats["preserved_uuids"] >= 4  # sig, alert, task, audit event_id


# --- Diff ---


class TestDiff:
    def test_two_runs_differing_only_in_noise_are_equivalent(self):
        result = eh.diff_snapshots(run_a(), run_b())
        assert result.equivalent, eh.render_report(result)

    def test_row_content_difference_detected(self):
        a, b = run_a(), run_b()
        b["tables"]["alerts"][0]["severity"] = "CRITICAL"
        result = eh.diff_snapshots(a, b)
        assert not result.equivalent
        assert "alerts" in result.mismatched_tables

    def test_missing_row_detected(self):
        a, b = run_a(), run_b()
        b["tables"]["signals"] = []
        result = eh.diff_snapshots(a, b)
        assert not result.equivalent
        assert "signals" in result.mismatched_tables

    def test_duplicate_row_detected(self):
        # At-least-once delivery producing a second audit row must show up:
        # multiset semantics, not set semantics.
        a, b = run_a(), run_b()
        dup = copy.deepcopy(b["tables"]["audit_log"][0])
        dup["audit_id"] = str(uuid.uuid4())
        b["tables"]["audit_log"].append(dup)
        result = eh.diff_snapshots(a, b)
        assert not result.equivalent
        assert "audit_log" in result.mismatched_tables

    def test_deterministic_id_drift_not_masked_by_renaming(self):
        # If one transport corrupts a deterministic id into some other value,
        # renaming must NOT absorb it: run A carries the true id (preserved),
        # run B carries an unknown uuid (renamed) — rows must not match.
        a, b = run_a(), run_b()
        b["tables"]["signals"][0]["signal_id"] = RANDOM_B
        result = eh.diff_snapshots(a, b)
        assert not result.equivalent
        assert "signals" in result.mismatched_tables

    def test_ignore_column_is_applied_and_reported(self):
        a, b = run_a(), run_b()
        b["tables"]["audit_log"][0]["detail"] = {"event_type": "signal.received", "topic": "ocean.signals"}
        strict = eh.diff_snapshots(a, b)
        assert not strict.equivalent
        loose = eh.diff_snapshots(a, b, ignore=["audit_log.detail.topic"])
        assert loose.equivalent
        assert "audit_log.detail.topic" in loose.ignored
        assert "audit_log.detail.topic" in eh.render_report(loose)

    def test_report_names_table_and_shows_counts(self):
        a, b = run_a(), run_b()
        b["tables"]["signals"] = []
        report = eh.render_report(eh.diff_snapshots(a, b))
        assert "signals" in report
        assert "NOT EQUIVALENT" in report

    def test_equivalent_report_says_so(self):
        report = eh.render_report(eh.diff_snapshots(run_a(), run_b()))
        assert "EQUIVALENT" in report

    def test_diff_accepts_raw_snapshots_and_normalizes(self):
        # diff_snapshots takes raw captures; callers never pre-normalize.
        a = run_a()
        assert a["tables"]["signals"][0]["received_at"] != eh.TS_TOKEN
        result = eh.diff_snapshots(a, run_b())
        assert result.equivalent


class TestAmbiguityWarning:
    def test_indistinguishable_rows_with_random_ids_flagged(self):
        # Two missed-call interactions for the same patient are identical
        # after normalization except for their random ids; token assignment
        # between them is arbitrary, so the harness must surface the tie.
        snap = run_a()
        row = copy.deepcopy(snap["tables"]["interactions"][0])
        row["interaction_id"] = str(uuid.uuid4())
        snap["tables"]["interactions"].append(row)
        norm = eh.normalize_snapshot(snap)
        groups = norm["meta"]["ambiguous_row_groups"]
        assert any(g["table"] == "interactions" for g in groups)

    def test_no_warning_when_rows_distinct(self):
        norm = eh.normalize_snapshot(run_a())
        assert norm["meta"]["ambiguous_row_groups"] == []


# --- Capture plumbing (no live DB in tests) ---


class TestCapture:
    def test_capture_query_uses_json_agg(self):
        sql = eh.capture_query("signals")
        assert "json_agg" in sql
        assert "signals" in sql

    def test_capture_query_rejects_unknown_table(self):
        with pytest.raises(ValueError, match="not a captured table"):
            eh.capture_query("pg_shadow; DROP TABLE x")

    def test_capture_tables_cover_classification_map(self):
        assert set(eh.CAPTURE_TABLES) == set(eh.COLUMN_CLASSES)
        assert "audit_log" in eh.CAPTURE_TABLES

    def test_capture_snapshot_shells_out_per_table(self):
        calls: list[list[str]] = []

        def fake_runner(cmd: list[str]) -> str:
            calls.append(cmd)
            return "[]"

        snap = eh.capture_snapshot(
            scenario=SCENARIO,
            label="kafka",
            psql_cmd=["psql", "-h", "localhost"],
            runner=fake_runner,
        )
        assert len(calls) == len(eh.CAPTURE_TABLES)
        assert snap["meta"]["label"] == "kafka"
        assert snap["meta"]["scenario"] == "smoke"
        assert set(snap["tables"]) == set(eh.CAPTURE_TABLES)
        assert sorted(snap["deterministic_ids"]) == sorted(eh.deterministic_ids(SCENARIO))

    def test_snapshot_round_trips_through_json(self, tmp_path):
        snap = run_a()
        path = tmp_path / "snap.json"
        path.write_text(json.dumps(snap))
        loaded = json.loads(path.read_text())
        result = eh.diff_snapshots(loaded, run_b())
        assert result.equivalent
