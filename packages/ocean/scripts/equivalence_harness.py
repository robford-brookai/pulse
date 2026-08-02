#!/usr/bin/env python3
"""Equivalence harness for the EventBridge migration gate (task 8.1, DNA-773).

Captures the operational graph tables and ``audit_log`` after a
``call-simulator`` + ``sim-driver`` run, normalizes exactly the values that are
wall-clock or identifier-random by construction, and diffs two captures. 8.2
runs one capture against the Kafka path and one against the LocalStack path;
the diff gates the teardown (local-event-stack spec, "Simulation reaches
identical state on either transport").

What gets normalized, and why nothing else does
------------------------------------------------

Every value in a captured row is classified, per column, as exactly one of:

- PRESERVE   — compared verbatim. Scenario literals (patient/clinic ids),
               enums, severities, numeric readings, event types.
- TIMESTAMP  — every timestamp in this system is wall-clock at write time
               (``datetime.now`` in sim-driver, call-simulator, agent-worker,
               event-store, graph-projection; ``now()`` server defaults).
               No simulated-time timestamps exist, so all timestamp columns
               collapse to a token, keeping only NULL vs non-NULL.
- IDENTIFIER — value-level rule. sim-driver derives its event/entity ids
               deterministically (sha256 of the scenario key), and
               control-plane derives task ids deterministically from alert
               ids (uuid5). Those must survive verbatim — a transport that
               corrupts one must fail the gate. Only UUIDs *outside* that
               deterministic universe (uuid4 from call-simulator,
               agent-worker, event-store's audit_id, graph-projection's
               outcome uuid5 over a random engagement id) are renamed, and
               renamed consistently: one bijective map per snapshot, so
               referential structure is still compared.
- SEQUENCE   — Postgres SERIAL surrogate keys. Delivery-order-dependent by
               construction; dropped (the row's natural key identifies it).

A column or table this map does not know is an error, never a silent
pass-through: schema drift must force a conscious classification.

``audit_log.detail.topic`` records the transport topic and genuinely differs
between the Kafka and EventBridge paths. It is NOT normalized here: 8.2 must
exclude it explicitly (``--ignore audit_log.detail.topic``), and the report
records every exclusion, so the gate stays honest about what it ignored.

Usage
-----

    # after a sim run on each transport (stack from infra/docker-compose.yml):
    python scripts/equivalence_harness.py capture \
        --scenario services/sim-driver/scenarios/smoke_test.yaml \
        --label kafka --out kafka.json

    python scripts/equivalence_harness.py diff kafka.json eventbridge.json \
        --ignore audit_log.detail.topic

Exit code 0 iff equivalent. No PHI: the harness is only ever pointed at the
local simulation stack, whose data is synthetic by construction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TS_TOKEN = "<ts>"  # noqa: S105 — replacement token for wall-clock values, not a secret
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ISO_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?$")

P, TS, ID, SEQ = "preserve", "timestamp", "identifier", "sequence"

#: Every captured table, every column, classified. An unknown column raises.
COLUMN_CLASSES: dict[str, dict[str, str]] = {
    "patients": {
        "patient_id": ID,
        "clinic_id": P,
        "enrollment_status": P,
        "enrolled_at": TS,
        "updated_at": TS,
        "last_event_id": ID,
    },
    "signals": {
        "signal_id": ID,
        "patient_id": ID,
        "signal_type": P,
        "value": P,
        "unit": P,
        "received_at": TS,
        "anomalous": P,
        "last_event_id": ID,
        "last_event_at": TS,
    },
    "alerts": {
        "alert_id": ID,
        "patient_id": ID,
        "alert_type": P,
        "severity": P,
        "status": P,
        "source_system": P,
        # pgvector column (0006). Populated only by an explicit stacte-bridge
        # /sync, so a sim capture holds NULLs; compared verbatim so a
        # transport that somehow touched it would fail the gate.
        "embedding": P,
        "created_at": TS,
        "updated_at": TS,
        "correlation_id": ID,
        "last_event_id": ID,
    },
    "tasks": {
        "task_id": ID,
        "alert_id": ID,
        "patient_id": ID,
        "task_type": P,
        "priority": P,
        "status": P,
        "assigned_to": P,
        "embedding": P,  # pgvector (0006), see alerts.embedding
        "created_at": TS,
        "updated_at": TS,
        "last_event_id": ID,
    },
    "interactions": {
        "interaction_id": ID,
        "task_id": ID,
        "patient_id": ID,
        "interaction_type": P,
        "outcome": P,
        "embedding": P,  # pgvector (0006), see alerts.embedding
        "started_at": TS,
        "completed_at": TS,
        "last_event_at": TS,
        "last_event_id": ID,
    },
    "outcomes": {
        "outcome_id": ID,
        "interaction_id": ID,
        "patient_id": ID,
        "outcome_type": P,
        "resolution_status": P,
        "notes": P,
        "embedding": P,  # pgvector (0006), see alerts.embedding
        "recorded_at": TS,
        "last_event_id": ID,
    },
    "tickets": {
        "ticket_id": ID,
        # human_id comes from a per-category sequence: deterministic given one
        # delivery order, order-dependent across orders. Preserved — a swap
        # between otherwise-identical rows is invisible under multiset
        # comparison, and a swap between differing rows should be seen.
        "human_id": P,
        "category": P,
        "priority": P,
        "status": P,
        "patient_id": ID,
        "description": P,
        "waiting_reason": P,
        "created_at": TS,
        "updated_at": TS,
        "correlation_id": ID,
        "last_event_id": ID,
        "last_event_at": TS,
    },
    "ticket_tasks": {"ticket_id": ID, "task_id": ID, "linked_at": TS},
    "alert_tasks": {"alert_id": ID, "task_id": ID, "linked_at": TS},
    "ticket_alerts": {"ticket_id": ID, "alert_id": ID, "linked_at": TS},
    "task_escalation_state": {
        "id": SEQ,
        "entity_type": P,
        "entity_id": ID,
        "priority_at_creation": P,
        "current_priority": P,
        "created_at": TS,
        "last_checked_at": TS,
        "escalated_at": TS,
        "escalation_count": P,
    },
    "audit_log": {
        "audit_id": ID,
        "event_id": ID,
        "action_type": P,
        "actor_id": P,
        "source_system": P,
        "entity_type": P,
        "entity_id": ID,
        "timestamp": TS,
        "detail": ID,  # JSONB: strings inside are scanned by the identifier rule
        "recorded_at": TS,
    },
}

#: Capture order is also token-assignment order — keep it fixed.
CAPTURE_TABLES: tuple[str, ...] = tuple(COLUMN_CLASSES)

#: Tables deliberately not captured, so the choice is visible: ``events`` is
#: the ledger (its content is compared through the audit trail), ``simulations``
#: is run bookkeeping, ``slack_messages``/``failed_webhooks``/``connector_health``/
#: ``ai_drafts``/``cdc_resume_tokens`` are operational side-state, and the
#: logistics tables (``fulfillments``, ``returns``, ``device_associations``)
#: are fed by CDC, not by the simulators.
EXCLUDED_TABLES: tuple[str, ...] = (
    "events",
    "simulations",
    "slack_messages",
    "failed_webhooks",
    "connector_health",
    "ai_drafts",
    "cdc_resume_tokens",
    "fulfillments",
    "returns",
    "device_associations",
    "alert_snoozes",
)


class UnclassifiedColumnError(ValueError):
    """A captured table or column the classification map does not know."""


# --- Deterministic-ID universe ---


def sim_uuid(key: str) -> str:
    """sim-driver's derivation: UUID over the first 16 bytes of sha256(key)."""
    return str(uuid.UUID(bytes=hashlib.sha256(key.encode()).digest()[:16]))


def deterministic_ids(scenario: dict) -> set[str]:
    """The universe of identifiers derivable from the scenario alone.

    Mirrors, deliberately and narrowly, the three deterministic derivations in
    the services: sim-driver's per-signal ids (``PatientSimulator._deterministic_id``),
    sim-driver's scenario bookends (``ScenarioEngine._publish_bookend``), and
    control-plane's task ids (``uuid5(NAMESPACE_URL, f"task-{alert_id}")`` in
    ``handlers/alerts.py``). If one of those derivations changes, this must
    change with it — the normalization stats in every snapshot exist so a
    silent divergence (everything suddenly renamed) is visible in review.
    """
    name = scenario["name"]
    ids: set[str] = set()
    for bookend in ("scenario.started", "scenario.completed"):
        ids.add(sim_uuid(f"sim:{name}:{bookend}"))
    for patient in scenario.get("patients", []):
        pid = patient["patient_id"]
        for idx, signal in enumerate(patient.get("signals", [])):
            ids.add(sim_uuid(f"sim:{name}:{pid}:{idx}"))
            if signal.get("anomalous"):
                alert_id = sim_uuid(f"sim:{name}:{pid}:{idx}_alert")
                ids.add(alert_id)
                ids.add(str(uuid.uuid5(uuid.NAMESPACE_URL, f"task-{alert_id}")))
    return ids


# --- Normalization ---


def _classify_columns(table: str, rows: list[dict]) -> dict[str, str]:
    classes = COLUMN_CLASSES.get(table)
    if classes is None:
        raise UnclassifiedColumnError(f"table {table!r} is not in the classification map")
    for row in rows:
        unknown = set(row) - set(classes)
        if unknown:
            cols = ", ".join(f"{table}.{c}" for c in sorted(unknown))
            raise UnclassifiedColumnError(
                f"unclassified column(s): {cols} — classify them in COLUMN_CLASSES before capturing"
            )
    return classes


def _walk_strings(value: Any, fn: Callable[[str], str]) -> Any:
    """Apply fn to every string inside a JSON-shaped value."""
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: _walk_strings(v, fn) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_walk_strings(v, fn) for v in value]
    return value


def _normalize_ts(value: Any) -> Any:
    return None if value is None else TS_TOKEN


@dataclass
class _Renamer:
    """Bijective random-uuid → token map, assignment order = first sight."""

    universe: frozenset[str]
    mapping: dict[str, str] = field(default_factory=dict)
    preserved: int = 0
    renamed: int = 0

    def rewrite(self, text: str) -> str:
        def sub(match: re.Match[str]) -> str:
            value = match.group(0).lower()
            if value in self.universe:
                self.preserved += 1
                return value
            if value not in self.mapping:
                self.mapping[value] = f"<uuid-{len(self.mapping) + 1}>"
            self.renamed += 1
            return self.mapping[value]

        return UUID_RE.sub(sub, text)

    def rewrite_value(self, value: Any) -> Any:
        def per_string(s: str) -> str:
            if _ISO_TS_RE.match(s):
                return TS_TOKEN
            return self.rewrite(s)

        return _walk_strings(value, per_string)


def _prepared_rows(snapshot: dict) -> dict[str, list[dict]]:
    """Pass 1: timestamps tokenized, SEQ dropped, ids untouched; validates columns."""
    prepared: dict[str, list[dict]] = {}
    for table, rows in snapshot["tables"].items():
        classes = _classify_columns(table, rows)
        out = []
        for row in rows:
            new: dict[str, Any] = {}
            for col, value in row.items():
                cls = classes[col]
                if cls == SEQ:
                    continue
                new[col] = _normalize_ts(value) if cls == TS else value
            out.append(new)
        prepared[table] = out
    return prepared


def _blind_key(row: dict, classes: dict[str, str], universe: frozenset[str], mapping: dict[str, str]) -> str:
    """Canonical sort key with every genuinely-unseen UUID blinded to one token.

    Token assignment must not depend on the random values themselves, so rows
    are ordered by what they look like *after* renaming would erase those
    values — this key is that view. UUIDs the renamer has already mapped keep
    their assigned token: those tokens were themselves assigned in canonical
    order, so they are safe to sort by, and they are what distinguishes rows
    like the per-call audit entries (mapped entity_id + fresh event_id and
    audit_id). Blinding them too made all such rows tie, pairing fresh tokens
    with mapped ones in physical capture order — two runs differing only in
    row order then diffed as NOT EQUIVALENT (found by the live 8.2 runs).
    """

    def blind(text: str) -> str:
        def sub(match: re.Match[str]) -> str:
            value = match.group(0).lower()
            if value in universe:
                return value
            return mapping.get(value, "<uuid>")

        return UUID_RE.sub(sub, text)

    def per_string(s: str) -> str:
        return TS_TOKEN if _ISO_TS_RE.match(s) else blind(s)

    projected = {col: _walk_strings(v, per_string) if classes[col] == ID else v for col, v in row.items()}
    return json.dumps(projected, sort_keys=True, default=str)


def normalize_snapshot(snapshot: dict) -> dict:
    """Return the snapshot with noise-by-construction removed, nothing else.

    Two-pass: rows are first sorted by a key blind to their *unseen* random
    uuids (uuids already renamed while processing earlier tables keep their
    assigned token), then tokens are assigned by first sight in that canonical
    order — so two runs whose states differ only in random identifiers
    normalize identically. Table order in CAPTURE_TABLES is therefore part of
    the canonicalization: graph tables assign the tokens audit_log sorts by.
    """
    universe = frozenset(snapshot.get("deterministic_ids", []))
    prepared = _prepared_rows(snapshot)
    renamer = _Renamer(universe=universe)
    ambiguous: list[dict] = []
    tables: dict[str, list[dict]] = {}

    for table in prepared:
        classes = COLUMN_CLASSES[table]
        keyed = sorted(
            ((_blind_key(r, classes, universe, renamer.mapping), r) for r in prepared[table]),
            key=lambda kr: kr[0],
        )

        # Ties among rows that still contain random uuids make token
        # assignment between them arbitrary; surface every such group.
        key_counts = Counter(k for k, _ in keyed)
        for key, count in sorted(key_counts.items()):
            if count > 1 and "<uuid>" in key:
                ambiguous.append({"table": table, "rows": count, "shape": key})

        tables[table] = [
            {col: renamer.rewrite_value(v) if classes[col] == ID else v for col, v in row.items()} for _, row in keyed
        ]

    return {
        "meta": {
            **snapshot.get("meta", {}),
            "normalization_stats": {
                "preserved_uuids": renamer.preserved,
                "renamed_uuids": renamer.renamed,
                "distinct_renamed": len(renamer.mapping),
            },
            "ambiguous_row_groups": ambiguous,
        },
        "tables": tables,
    }


# --- Diff ---


@dataclass
class DiffResult:
    equivalent: bool
    ignored: list[str]
    ignored_audit_events: list[str]
    table_counts: dict[str, tuple[int, int]]
    only_in_a: dict[str, list[str]]
    only_in_b: dict[str, list[str]]
    warnings: list[str]

    @property
    def mismatched_tables(self) -> set[str]:
        return set(self.only_in_a) | set(self.only_in_b)


def _drop_ignored(tables: dict[str, list[dict]], ignore: Iterable[str]) -> dict[str, list[dict]]:
    """Remove explicitly ignored ``table.column`` / ``table.column.jsonkey`` paths."""
    out = {t: [dict(r) for r in rows] for t, rows in tables.items()}
    for spec_path in ignore:
        parts = spec_path.split(".")
        if len(parts) not in (2, 3):
            raise ValueError(f"--ignore takes table.column or table.column.jsonkey, got {spec_path!r}")
        table, col = parts[0], parts[1]
        for row in out.get(table, []):
            if len(parts) == 2:
                row.pop(col, None)
            elif isinstance(row.get(col), dict):
                row[col].pop(parts[2], None)
    return out


def _drop_audit_events(snapshot: dict, event_types: list[str]) -> dict:
    """Drop audit_log rows whose ``detail.event_type`` is excluded, pre-normalization.

    Must run on the raw capture: excluded event types exist precisely because
    their row count differs between sides (e.g. uptime-driven heartbeats), and
    rows removed after token assignment would shift every token numbered after
    them in canonical order, faulting rows that actually match.
    """
    if not event_types:
        return snapshot
    excluded = set(event_types)
    out = {**snapshot, "tables": dict(snapshot["tables"])}
    rows = out["tables"].get("audit_log", [])
    out["tables"]["audit_log"] = [
        r for r in rows if not (isinstance(r.get("detail"), dict) and r["detail"].get("event_type") in excluded)
    ]
    return out


def diff_snapshots(
    a: dict,
    b: dict,
    ignore: list[str] | None = None,
    ignore_audit_events: list[str] | None = None,
) -> DiffResult:
    """Diff two raw captures. Rows compare as multisets of normalized rows."""
    ignore = list(ignore or [])
    ignore_audit_events = list(ignore_audit_events or [])
    a = _drop_audit_events(a, ignore_audit_events)
    b = _drop_audit_events(b, ignore_audit_events)
    norm_a, norm_b = normalize_snapshot(a), normalize_snapshot(b)
    tables_a = _drop_ignored(norm_a["tables"], ignore)
    tables_b = _drop_ignored(norm_b["tables"], ignore)

    warnings = [
        f"{side}: {g['rows']} indistinguishable {g['table']} rows carry random ids; "
        "token assignment between them is arbitrary"
        for side, norm in (("A", norm_a), ("B", norm_b))
        for g in norm["meta"]["ambiguous_row_groups"]
    ]

    only_in_a: dict[str, list[str]] = {}
    only_in_b: dict[str, list[str]] = {}
    table_counts: dict[str, tuple[int, int]] = {}
    for table in sorted(set(tables_a) | set(tables_b)):
        rows_a = Counter(json.dumps(r, sort_keys=True, default=str) for r in tables_a.get(table, []))
        rows_b = Counter(json.dumps(r, sort_keys=True, default=str) for r in tables_b.get(table, []))
        table_counts[table] = (sum(rows_a.values()), sum(rows_b.values()))
        extra_a = list((rows_a - rows_b).elements())
        extra_b = list((rows_b - rows_a).elements())
        if extra_a:
            only_in_a[table] = extra_a
        if extra_b:
            only_in_b[table] = extra_b

    return DiffResult(
        equivalent=not only_in_a and not only_in_b,
        ignored=ignore,
        ignored_audit_events=ignore_audit_events,
        table_counts=table_counts,
        only_in_a=only_in_a,
        only_in_b=only_in_b,
        warnings=warnings,
    )


def render_report(result: DiffResult, max_rows: int = 5) -> str:
    lines = ["EQUIVALENT" if result.equivalent else "NOT EQUIVALENT", ""]
    if result.ignored or result.ignored_audit_events:
        lines.append("Explicitly ignored (excluded from the comparison, by request):")
        lines.extend(f"  - {path}" for path in result.ignored)
        lines.extend(
            f"  - audit_log rows with detail.event_type={event_type}" for event_type in result.ignored_audit_events
        )
        lines.append("")
    lines.append("Rows compared per table (A/B):")
    lines.extend(f"  {table}: {ca}/{cb}" for table, (ca, cb) in sorted(result.table_counts.items()))
    for label, side in (("Only in A", result.only_in_a), ("Only in B", result.only_in_b)):
        for table, rows in sorted(side.items()):
            lines.append("")
            lines.append(f"{label} — {table} ({len(rows)} row(s)):")
            lines.extend(f"  {row}" for row in rows[:max_rows])
            if len(rows) > max_rows:
                lines.append(f"  ... and {len(rows) - max_rows} more")
    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"  - {w}" for w in result.warnings)
    return "\n".join(lines)


# --- Capture ---


def capture_query(table: str) -> str:
    if table not in COLUMN_CLASSES:
        raise ValueError(f"{table!r} is not a captured table")
    return f"SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM {table} t"


DEFAULT_PSQL_CMD = "docker compose -f infra/docker-compose.yml exec -T postgres psql -U ocean -d ocean"


def _run_psql(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout  # noqa: S603 — operator-supplied command


def capture_snapshot(
    scenario: dict,
    label: str,
    psql_cmd: list[str],
    runner: Callable[[list[str]], str] = _run_psql,
) -> dict:
    """Capture every table in CAPTURE_TABLES via psql, as one JSON document.

    Raw values are stored unmodified; normalization happens at diff time, so a
    better normalization can be re-applied to old captures.
    """
    tables = {}
    for table in CAPTURE_TABLES:
        out = runner([*psql_cmd, "-At", "-c", capture_query(table)])
        tables[table] = json.loads(out)
    return {
        "meta": {"scenario": scenario["name"], "label": label},
        "deterministic_ids": sorted(deterministic_ids(scenario)),
        "tables": tables,
    }


# --- CLI ---


def _load_scenario(path: str) -> dict:
    import yaml

    with Path(path).open() as fh:
        return yaml.safe_load(fh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="capture graph tables + audit_log after a sim run")
    cap.add_argument("--scenario", required=True, help="scenario yaml the run used")
    cap.add_argument("--label", required=True, help="which transport this capture is (e.g. kafka, eventbridge)")
    cap.add_argument("--out", required=True, help="snapshot file to write")
    cap.add_argument("--psql-cmd", default=DEFAULT_PSQL_CMD, help="command that reaches psql on the stack's postgres")

    dif = sub.add_parser("diff", help="diff two captures; exit 0 iff equivalent")
    dif.add_argument("snapshot_a")
    dif.add_argument("snapshot_b")
    dif.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="TABLE.COLUMN[.JSONKEY]",
        help="explicitly exclude a field; every exclusion is recorded in the report",
    )
    dif.add_argument(
        "--ignore-audit-event",
        action="append",
        default=[],
        metavar="EVENT_TYPE",
        help=(
            "exclude audit_log rows with this detail.event_type (e.g. uptime-driven "
            "connector.heartbeat); recorded in the report like column ignores"
        ),
    )
    dif.add_argument("--report", help="also write the report to this path")

    args = parser.parse_args(argv)

    if args.command == "capture":
        snapshot = capture_snapshot(
            scenario=_load_scenario(args.scenario),
            label=args.label,
            psql_cmd=shlex.split(args.psql_cmd),
        )
        Path(args.out).write_text(json.dumps(snapshot, indent=2, default=str))
        stats = normalize_snapshot(snapshot)["meta"]["normalization_stats"]
        print(f"captured {sum(len(r) for r in snapshot['tables'].values())} rows to {args.out}")
        print(f"normalization preview: {stats}")
        return 0

    result = diff_snapshots(
        json.loads(Path(args.snapshot_a).read_text()),
        json.loads(Path(args.snapshot_b).read_text()),
        ignore=args.ignore,
        ignore_audit_events=args.ignore_audit_event,
    )
    report = render_report(result)
    print(report)
    if args.report:
        Path(args.report).write_text(report + "\n")
    return 0 if result.equivalent else 1


if __name__ == "__main__":
    sys.exit(main())
