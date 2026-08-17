"""Load the committed synthetic seed projection into one Twenty target (twenty-dev-instance 2.5).

The population a demo drags comes from `generated/twenty_seed_dev.json` — a committed, checksummed
deterministic projection, never a live generator run (design: "Seed from a committed deterministic
projection"). The generator needs a Java toolchain, emits into an untracked tree, and mints no
canonical spine identifier; the projection carries one per patient, minted deterministically from
the generator's record UUID by `mint_canonical_patient_id`, so repeated derivation yields the same
values. Every value in the projection is synthetic — no real patient data, ever.

Target resolution and receipt posture are `twenty_deploy`'s, verbatim — this module imports them
rather than restating them:

- **Verify before load.** The projection's recorded checksum is recomputed over its records and a
  mismatch is refused naming both digests, before the target is even read. A board record missing
  its status as-of stamp is refused the same way: a null stamp means the first drag is refused for
  a missing effective time, so an incomplete record never reaches the workspace.
- **Idempotent, keyed on natural keys.** Twenty's internal record ids are not stable across
  instances, so records match by natural key — `code` for programs, `canonicalPatientId` for
  patients, the (patient, program) pair for patientPrograms. Create when absent, patch when
  drifted, no change when matching. Keys the workspace carries but the projection does not name
  (server-side base columns) are not drift.
- **Never delete.** The transport protocol exposes list, batch-create, and patch — no delete verb
  exists to call, so a workspace record outside the projection is left alone by construction.
- **Receipts carry object names, counts, and the checksum — never workspace content.** No record
  ids, no field values, no response bodies; `TransportError` (imported) has no field for a body.

Writes are chunked to the instance's 60-records-per-call batch limit and paced to its
100-requests-per-minute rate limit by `Pacer`, rather than relying on the instance to reject
excess. The REST endpoint shapes below are this repo's pin, unverified against a live instance —
the same posture as `twenty_deploy`'s metadata pin; wave 3 is the ground truth.

To edit the projection: change `records`, recompute `records_checksum(records)`, and commit both —
the diff is the review.

Run: uv run python -m pulse_core.twenty_seed --target dev [--dry-run]   (task twenty:seed)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from pulse_core.twenty_deploy import (
    DEFAULT_TIMEOUT_SECONDS,
    TARGET_NAMES,
    DeployError,
    RemoteRecord,
    Target,
    TransportError,
    resolve_target,
)

SEED_PATH = Path(__file__).parent / "generated" / "twenty_seed_dev.json"
SEED_FORMAT = "pulse-core/twenty-seed@1"

#: Namespace the canonical spine identifier is minted under:
#: `uuid5(NAMESPACE_URL, "https://brook.ai/pulse/spine/patient")`. Fixed forever — changing it
#: re-identifies every seeded patient.
SPINE_NAMESPACE = uuid.UUID("b58175d1-2eb0-54c4-b5d0-6a83d33acd47")

#: The dev instance's limits (twenty-dev-instance task 2.5). The loader stays inside them by
#: construction — chunked batch creates, one paced request at a time — rather than retrying 429s.
MAX_RECORDS_PER_CALL = 60
MAX_REQUESTS_PER_MINUTE = 100

REST_ROOT = "/rest"

#: Board objects and the as-of stamps each record must carry to be draggable on arrival. A null
#: stamp makes the first drag unresolvable to an effective time, so it is refused at load.
BOARD_AS_OF_FIELDS: Mapping[str, tuple[str, ...]] = {
    "patientPrograms": ("lifecycleStatusAsOf", "qualificationStatusAsOf"),
}


@dataclass(frozen=True)
class RelationSpec:
    """How a child record reaches its parent's workspace id: by the parent's natural key.

    `field` is the foreign-key column sent to Twenty (the webhook-flat `patientId` shape);
    `local` is the child's own denormalized copy of the parent's key value.
    """

    field: str
    parent: str
    local: str


@dataclass(frozen=True)
class SeedObject:
    """One seeded object: its REST plural, its natural key, and its parents."""

    plural: str
    key_fields: tuple[str, ...]
    relations: tuple[RelationSpec, ...] = ()


#: Load order — parents strictly before children, so a child's relation always resolves against a
#: workspace state that already contains everything created this run.
SEED_OBJECTS: tuple[SeedObject, ...] = (
    SeedObject(plural="programs", key_fields=("code",)),
    SeedObject(plural="patients", key_fields=("canonicalPatientId",)),
    SeedObject(
        plural="patientPrograms",
        key_fields=("canonicalPatientId", "programCode"),
        relations=(
            RelationSpec(field="patientId", parent="patients", local="canonicalPatientId"),
            RelationSpec(field="programId", parent="programs", local="programCode"),
        ),
    ),
)


def mint_canonical_patient_id(source_record_id: str) -> str:
    """The canonical spine id for one generator record — deterministic, so re-derivation agrees."""
    return str(uuid.uuid5(SPINE_NAMESPACE, source_record_id))


# --- Projection ----------------------------------------------------------------------------------


def records_checksum(records: Mapping[str, Any]) -> str:
    """The projection's identity: sha256 over the canonical JSON serialization of its records."""
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class Projection:
    """The verified seed population: per-object records, and the checksum they hashed to."""

    checksum: str
    records: Mapping[str, tuple[Mapping[str, Any], ...]]


def _completeness_findings(records: Mapping[str, tuple[Mapping[str, Any], ...]]) -> list[str]:
    """Every way this population would land undraggable or unkeyable, each finding named."""
    findings = []
    for obj in SEED_OBJECTS:
        for record in records.get(obj.plural, ()):
            fields = record.get("fields", {})
            for key_field in obj.key_fields:
                if not fields.get(key_field):
                    findings.append(f"a {obj.plural} record has no {key_field} — its natural key is incomplete")
            for stamp in BOARD_AS_OF_FIELDS.get(obj.plural, ()):
                if not fields.get(stamp):
                    findings.append(f"a {obj.plural} record has no {stamp} — its first drag would be refused")
    return findings


def load_projection(path: Path) -> Projection:
    """Read and verify one projection file; every refusal is a `DeployError` naming its reason."""
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError:
        msg = f"seed projection {path} is missing"
        raise DeployError(msg) from None
    except json.JSONDecodeError as error:
        msg = f"seed projection {path.name} is not valid JSON: {error}"
        raise DeployError(msg) from None

    if body.get("format") != SEED_FORMAT:
        msg = f"seed projection {path.name} has format {body.get('format')!r}, expected {SEED_FORMAT!r}"
        raise DeployError(msg)

    raw = body.get("records", {})
    if set(raw) != {obj.plural for obj in SEED_OBJECTS}:
        msg = f"seed projection {path.name} does not describe exactly the seeded objects"
        raise DeployError(msg)
    records = {plural: tuple(raw[plural]) for plural in raw}

    recorded = str(body.get("checksum", ""))
    computed = records_checksum(raw)
    if recorded != computed:
        msg = f"seed projection {path.name} failed its checksum — recorded {recorded}, computed {computed}"
        raise DeployError(msg)

    if findings := _completeness_findings(records):
        raise DeployError(f"seed projection {path.name} is incomplete — refusing to load:\n" + "\n".join(findings))

    return Projection(checksum=computed, records=records)


# --- Matching ------------------------------------------------------------------------------------


def natural_key(obj: SeedObject, fields: Mapping[str, Any]) -> str:
    """The identity a record is matched under — never Twenty's internal id."""
    return "\x1f".join(str(fields[name]) for name in obj.key_fields)


def _index_remote(obj: SeedObject, records: Sequence[RemoteRecord]) -> dict[str, RemoteRecord]:
    """Workspace records by natural key. A record missing a key field can match nothing: skipped."""
    index = {}
    for record in records:
        if all(record.payload.get(name) for name in obj.key_fields):
            index[natural_key(obj, record.payload)] = record
    return index


def _resolve_relations(
    obj: SeedObject,
    fields: Mapping[str, Any],
    parents: Mapping[str, Mapping[str, RemoteRecord]],
    strict: bool,
) -> dict[str, str]:
    """Foreign-key columns for one child record, from its parents' workspace state.

    `strict` is False only for an offline dry run, where a to-be-created parent has no id yet;
    the relation column is then left out of the plan rather than invented.
    """
    resolved = {}
    for relation in obj.relations:
        parent = parents.get(relation.parent, {}).get(str(fields[relation.local]))
        if parent is None:
            if strict:
                msg = f"a {obj.plural} record's {relation.local} matches no {relation.parent} record on the target"
                raise DeployError(msg)
            continue
        resolved[relation.field] = parent.record_id
    return resolved


def _chunked(items: Sequence[Mapping[str, Any]], size: int) -> Iterator[Sequence[Mapping[str, Any]]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


# --- Transport -----------------------------------------------------------------------------------


class RecordsTransport(Protocol):
    """The core REST API boundary — the one place tests fake. List, batch-create, patch; no delete."""

    def list_records(self, plural: str) -> tuple[RemoteRecord, ...]: ...

    def create_batch(self, plural: str, payloads: tuple[Mapping[str, Any], ...]) -> tuple[RemoteRecord, ...]: ...

    def patch(self, plural: str, record_id: str, payload: Mapping[str, Any]) -> None: ...


class Pacer:
    """Spaces requests to the instance's rate limit, instead of letting it reject excess."""

    def __init__(
        self,
        per_minute: int = MAX_REQUESTS_PER_MINUTE,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = 60.0 / per_minute
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None and (remaining := self._interval - (now - self._last)) > 0:
            self._sleep(remaining)
            now = self._clock()
        self._last = now


class RestRecordsTransport:
    """The core REST API over HTTP, every request paced.

    Endpoint pin (unverified until wave 3, same posture as the metadata pin): list is
    `GET /rest/<plural>` paginated by `starting_after`, batch create is `POST /rest/batch/<plural>`,
    patch is `PATCH /rest/<plural>/<id>`. Failure bodies are dropped where they are read — see
    `TransportError`.
    """

    def __init__(self, target: Target, client: httpx.Client | None = None, pacer: Pacer | None = None) -> None:
        self._target = target
        self._pacer = pacer or Pacer()
        self._client = client or httpx.Client(
            base_url=target.url,
            headers={"Authorization": f"Bearer {target.token}"},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )

    def list_records(self, plural: str) -> tuple[RemoteRecord, ...]:
        records: list[RemoteRecord] = []
        cursor: str | None = None
        while True:
            self._pacer.wait()
            params: dict[str, Any] = {"limit": MAX_RECORDS_PER_CALL}
            if cursor is not None:
                params["starting_after"] = cursor
            response = self._client.get(f"{REST_ROOT}/{plural}", params=params)
            if response.status_code >= httpx.codes.BAD_REQUEST:
                raise TransportError(response.status_code)
            body = response.json()
            for record in body.get("data", {}).get(plural, ()):
                payload = {name: value for name, value in record.items() if name != "id"}
                records.append(RemoteRecord(record_id=str(record["id"]), payload=payload))
            page = body.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                return tuple(records)
            cursor = str(page["endCursor"])

    def create_batch(self, plural: str, payloads: tuple[Mapping[str, Any], ...]) -> tuple[RemoteRecord, ...]:
        self._pacer.wait()
        response = self._client.post(f"{REST_ROOT}/batch/{plural}", json=[dict(payload) for payload in payloads])
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise TransportError(response.status_code)
        created = []
        for record in response.json().get("data", {}).get(plural, ()):
            payload = {name: value for name, value in record.items() if name != "id"}
            created.append(RemoteRecord(record_id=str(record["id"]), payload=payload))
        return tuple(created)

    def patch(self, plural: str, record_id: str, payload: Mapping[str, Any]) -> None:
        self._pacer.wait()
        response = self._client.patch(f"{REST_ROOT}/{plural}/{record_id}", json=dict(payload))
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise TransportError(response.status_code)


# --- Receipt -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedReceipt:
    """What a load is worth attaching: which projection went where, and per-object counts.

    Object names, counts, and the checksum. No record ids, no field values, no response bodies.
    """

    target: str
    source: str
    checksum: str
    dry_run: bool
    objects: Mapping[str, Mapping[str, int]]
    failure: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "source": self.source,
            "checksum": self.checksum,
            "dryRun": self.dry_run,
            "objects": {plural: dict(counts) for plural, counts in self.objects.items()},
            "failure": self.failure,
        }


# --- Seed ----------------------------------------------------------------------------------------


def _apply_object(
    transport: RecordsTransport,
    obj: SeedObject,
    creates: Sequence[dict[str, Any]],
    updates: Sequence[tuple[str, dict[str, Any]]],
    remote: dict[str, RemoteRecord],
    counts: dict[str, int],
) -> str | None:
    """Send one object's planned writes, chunked and in plan order; counts reflect what went out."""
    try:
        for chunk in _chunked(creates, MAX_RECORDS_PER_CALL):
            for created in transport.create_batch(obj.plural, tuple(chunk)):
                remote[natural_key(obj, created.payload)] = created
            counts["create"] += len(chunk)
        for record_id, fields in updates:
            transport.patch(obj.plural, record_id, fields)
            counts["update"] += 1
    except TransportError as error:
        # Fail fast: a child create behind a failed parent create is guaranteed noise.
        return f"{obj.plural}: status {error.status}"
    return None


def seed(
    target: str,
    source_path: Path,
    transport: RecordsTransport | None,
    dry_run: bool = False,
) -> SeedReceipt:
    """Verify the projection, then upsert it into the target, parents before children.

    `transport` is `None` only offline: a dry run with no credentials plans against the empty-state
    assumption, `twenty_deploy.deploy`'s posture. A dry run's counts are the plan's; an apply's are
    what actually went out, so a run stopped by a failure reports the creates it made.
    """
    projection = load_projection(source_path)
    strict = transport is not None and not dry_run

    counts: dict[str, dict[str, int]] = {obj.plural: {"create": 0, "update": 0, "noop": 0} for obj in SEED_OBJECTS}
    parents: dict[str, dict[str, RemoteRecord]] = {}
    failure: str | None = None

    for obj in SEED_OBJECTS:
        if failure is not None:
            break
        remote = _index_remote(obj, transport.list_records(obj.plural)) if transport is not None else {}

        creates: list[dict[str, Any]] = []
        updates: list[tuple[str, dict[str, Any]]] = []
        for record in projection.records[obj.plural]:
            fields = dict(record["fields"])
            fields |= _resolve_relations(obj, fields, parents, strict=strict)
            current = remote.get(natural_key(obj, fields))
            if current is None:
                creates.append(fields)
            elif any(current.payload.get(name) != value for name, value in fields.items()):
                updates.append((current.record_id, fields))
            else:
                counts[obj.plural]["noop"] += 1

        if dry_run or transport is None:
            counts[obj.plural]["create"] = len(creates)
            counts[obj.plural]["update"] = len(updates)
        else:
            failure = _apply_object(transport, obj, creates, updates, remote, counts[obj.plural])

        parents[obj.plural] = remote

    return SeedReceipt(
        target=target,
        source=str(source_path),
        checksum=projection.checksum,
        dry_run=dry_run,
        objects=counts,
        failure=failure,
    )


# --- CLI -----------------------------------------------------------------------------------------


def _build_transport(target: str, env: Mapping[str, str], dry_run: bool) -> RecordsTransport | None:
    """The target's transport, or `None` for an offline dry run — `twenty_deploy`'s resolution."""
    try:
        resolved = resolve_target(target, env)
    except DeployError:
        if dry_run:
            return None
        raise
    return RestRecordsTransport(resolved)


def main(
    argv: list[str] | None = None,
    env: Mapping[str, str] | None = None,
    transport: RecordsTransport | None = None,
) -> int:
    """CLI entry point: verify, seed unless `--dry-run` plans only, print the receipt.

    `env` and `transport` are injected by tests; the CLI reads `os.environ` and builds the HTTP
    transport from the resolved target.
    """
    parser = argparse.ArgumentParser(description="Load the committed synthetic seed projection into one target.")
    parser.add_argument("--target", required=True, choices=TARGET_NAMES, help="which instance to seed")
    parser.add_argument("--source", type=Path, default=SEED_PATH, help="projection file to load")
    parser.add_argument("--dry-run", action="store_true", help="print per-object plan counts; write nothing")
    args = parser.parse_args(argv)

    environment = os.environ if env is None else env
    try:
        resolved_transport = (
            transport if transport is not None else _build_transport(args.target, environment, args.dry_run)
        )
        receipt = seed(
            target=args.target,
            source_path=args.source,
            transport=resolved_transport,
            dry_run=args.dry_run,
        )
    except DeployError as error:
        print(str(error))
        return 1

    print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
    return 1 if receipt.failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
