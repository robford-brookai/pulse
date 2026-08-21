#!/usr/bin/env python
"""Demo 3: the live kanban round trip (task 7.1) — a real Twenty instance, a served ledger API.

Per the roadmap's demo convention: a runnable script under `scripts/demo/`, exits nonzero on any
failed assertion, stays out of `task check`. Unlike Demos 1 and 2 this one is *live* — it needs a
reachable Twenty dev instance and a running `pulse_ledger.api_server`, so CI holds only the
smoke-parse contract (`tests/test_demo3_live_kanban_drag.py`) and task 7.2's verification wrap
runs the demo itself.

Nine assertions, in order:

1.  UID round-trip — the live `patientProgram` object and its `lifecycleStatus` field carry the
    `universalIdentifier` values `uid-map.json` minted (the F1 answer, held on v2.30).
2.  The lifecycle board exists, is KANBAN, and groups on the `lifecycleStatus` field. The board
    is identified by (live `patientProgram` object id, `KANBAN`, the app view's name) — the live
    `View` type carries no `universalIdentifier`, so a UID match is not available here.
3.  Column parity — the board's groups are exactly the catalog's `enrollment` states.
4.  Seed counts — every record in the committed projection is present in the workspace.
5.  As-of stamps — every seeded board record carries non-null status as-of stamps.
6.  Exactly one webhook is registered, scoped to the one mapped operation.
7.  A legal drag commits, driven through Twenty's REST API — the same write a UI drag issues.
8.  A replay probe proves, against the real committed event, that `effective_at` is the
    record's own `updatedAt` stamp (never the wall clock) and that a redelivery of the drag's
    idempotency key produces no second event.
9.  An illegal drag returns 200 `rejected` with exactly one new rejection note bound to the
    card (counted as `noteTargets` on the record id), and the state of record is unchanged.

**How the drag legs work (reworked, task 4.3).** The script PATCHes the card over Twenty's core
REST API (the same write a UI drag issues — task 7.2's hand drag is the UI-path acceptance step),
reads the record's own `updatedAt` back, then delivers the webhook body itself, signed with the
configured secret (`pulse_ledger.auth.sign`, Twenty's wire format) — this guarantees an event
exists for the drag without waiting on Twenty's own asynchronous webhook to land.

**Why steps 7 and 8 no longer read the commit's properties off that self-delivery.** With
Twenty's own webhook live (7.2), Twenty's delivery for this same PATCH now reliably commits
before the script's self-delivery arrives (task 4.1's live finding), so echo suppression (task
2.4) answers the self-delivery `noop reason=echo_of_record` — correctly, since the drag is
already committed, but the response the script can see no longer carries `effective_at` or
`event_id`. Worse, a genuine redelivery of that same committed target state is now *always*
`echo_of_record` too: `pulse_ledger.twenty.mapping.interpret` checks wire-state-equals-state-of-
record before it ever builds a command, so the D16 idempotency layer is unreachable for a
byte-identical repeat. Accepting `echo_of_record` as either step's pass would assert nothing —
it cannot distinguish "the ledger correctly deduplicated" from "this delivery never got far
enough to try."

`step_replay`'s probe (`_replay_probe_payload`) sidesteps this by naming the state the card was
dragged *from* as its target — never equal to the state it was dragged to, so it cannot be an
echo — while keeping the same subject, program, and `updated_at` as the committing drag, so it
carries the identical D16 idempotency key. The only way to answer that probe is a replay of the
original commit, whoever made it: Twenty's own webhook, or the script's own delivery in
`step_legal_drag` if it happened to win the race. That single probe response proves both
properties at once — its `state.effective_at` is the record's own stamp, and getting the
*original* `event_id` back rather than a new one is the no-second-event guarantee.

**Option considered and rejected: a new read-back endpoint.** Reading the committed event back
through a dedicated query surface (rather than the mapping's own idempotency behavior) was the
other option this task weighed. Rejected: it is new production surface with its own auth and
spec, for a property the ledger already proves through the wire protocol the demo already
speaks — the probe above needs no new endpoint, no new credential, and stays entirely within
`repo_change`'s offline-testable lane.

**Why there is a genesis-alignment delivery before the legal drag.** The ledger admits a subject
only at the catalog's entry state (`validate_genesis` — for `enrollment`, `pending_start`), so a
fresh subject's first committing drag is the one into that column. The alignment delivery declares
exactly that, with `record.updatedAt` fixed to the projection's own `lifecycleStatusAsOf` stamp so
its idempotency key is identical on every run: the first run commits the genesis, every later run
replays it, and no rerun ever earns a rejection note. The card is selected from the projection
records seeded at `pending_start` so Twenty's column and the ledger's genesis state start aligned;
after that, each run walks the non-`ended` legal cycle (`pending_start → active → on_hold →
active → ...`), keeping card and ledger in lockstep. If someone drags the selected card by hand
between runs — or re-seeds, which resets the card but not the ledger — the two diverge and the
legal leg fails with the catalog's receipt; rerun with a different `--card-index`.

**Endpoint pins.** The metadata REST reads reuse `twenty_deploy`'s verified surface. Three further
shapes are pinned here, each marked inline. The view read was **verified live 2026-08-17** by
7.2's first contact, which falsified the original pin twice: there is no `getCoreViews` on
`/graphql` — views are served by `getViews` on the metadata GraphQL — and the live `View` type
exposes no `universalIdentifier`, so the board is matched by object id, type and name instead.
The webhook listing was not exercised by that contact and stays unverified. The commentary read
counts `noteTargets` on `/rest/noteTargets` filtered by the record id — assertion 9's live run
falsified the original `/rest/comments` pin (v2.30 has no `comment` object), and the reworked
surface (task 6.7) is the note+noteTarget pair `pulse_ledger.twenty.client` now writes.

**PHI posture.** All seeded data is synthetic, and this script still handles it as if it were
not: the drag card is selected by index into a sorted-by-id list, never by name; workspace reads
project each record down to Twenty's internal id plus the pseudonymous key fields, timestamps,
and status values the assertions need, so no demographic field is ever retained; commentary reads
count `noteTarget` bindings matched on the record id and never fetch a note body. Everything printed is an identifier, a
count, a state, a timestamp, or a fixed code.

Configuration (never printed): `PULSE_TWENTY_<TARGET>_URL` / `PULSE_TWENTY_<TARGET>_TOKEN` for
Twenty (resolved by `twenty_deploy.resolve_target`, same as every credentialed target), and
`PULSE_LEDGER_API_URL` / `PULSE_LEDGER_TWENTY_WEBHOOK_SECRET` for the ledger API.

Usage:
    scripts/demo/demo3_live_kanban_drag.py [--target dev] [--card-index 0]
    scripts/demo/demo3_live_kanban_drag.py --help
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pulse_core.generated import TRANSITIONS
from pulse_core.twenty_deploy import (
    DEFAULT_TIMEOUT_SECONDS,
    GRAPHQL_PATH,
    METADATA_ROOT,
    DeployError,
    Target,
    resolve_target,
)
from pulse_core.twenty_model import load_uid_map, require_uid
from pulse_core.twenty_seed import (
    BOARD_AS_OF_FIELDS,
    SEED_OBJECTS,
    SEED_PATH,
    Pacer,
    load_projection,
    natural_key,
)
from pulse_core.twenty_validate import encode_option_value
from pulse_ledger.api import TWENTY_WEBHOOK_PATH
from pulse_ledger.auth import (
    NONCE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    TWENTY_WEBHOOK_SECRET_ENV,
    sign,
)

#: The ledger API's base URL — where task 2.1's served process answers. Named beside the secret
#: rather than derived: the demo may run from outside the cluster against a port-forward.
LEDGER_URL_ENV = "PULSE_LEDGER_API_URL"

#: The one v1 board this demo drives, restated from `pulse_ledger.twenty.mapping.V1_BOARD_MAPPINGS`
#: (decision 3). Restated, not imported as config: the demo asserts against the deployment's
#: choices, and reading them from the code under test would make the assertions circular.
BOARD_OBJECT = "patientProgram"
BOARD_OBJECT_PLURAL = "patientPrograms"
STATUS_FIELD = "lifecycleStatus"
SUBJECT_TYPE = "enrollment"
MAPPED_OPERATION = f"{BOARD_OBJECT}.updated"

#: The board's key in the app's vocabulary (task 6.1) — a label for receipts and failure messages,
#: no longer a live lookup: the live `View` type carries no `universalIdentifier`.
VIEW_KEY = "view.patient-program-lifecycle-board"

#: The board's `name` as `packages/twenty-app/src/views/patient-program-lifecycle-board.view.ts`
#: publishes it. Restated rather than imported, for the same reason as `BOARD_OBJECT` above.
VIEW_NAME = "Lifecycle Board"

#: The fields a workspace read is projected down to, per seeded object — Twenty's internal id
#: plus the pseudonymous natural-key fields, status values, and stamps the assertions need.
#: Nothing else survives the read (PHI posture above).
PROJECTED_FIELDS: Mapping[str, tuple[str, ...]] = {
    "programs": ("code",),
    "patients": ("canonicalPatientId",),
    BOARD_OBJECT_PLURAL: (
        "canonicalPatientId",
        "programCode",
        STATUS_FIELD,
        "lifecycleStatusAsOf",
        "qualificationStatusAsOf",
        "updatedAt",
    ),
}

#: Endpoint pin (verified live 2026-08-17): views are served by `getViews` on the metadata
#: GraphQL — there is no `getCoreViews` on `/graphql` — and the live `View` type exposes no
#: `universalIdentifier`. Selected fields are the ones assertions 2 and 3 compare.
VIEWS_QUERY = (
    "query Demo3Views { getViews { id name type objectMetadataId"
    " mainGroupByFieldMetadataId viewGroups { fieldValue isVisible } } }"
)

#: Endpoint pin (unverified — 7.2's live contact did not exercise this surface): webhooks read
#: over the metadata GraphQL, the surface task 4.1 registered through.
WEBHOOKS_QUERY = "query Demo3Webhooks { webhooks { id targetUrl operations } }"

#: Endpoint pin (reworked after 7.2's live falsification of `/rest/comments` — v2.30 has no
#: `comment` object): rejection commentary is a `note` bound to its record by a `noteTarget`.
#: Live-verified 2026-08-18: a noteTarget's relation to a *custom* object is the
#: `target`-prefixed column (`targetPatientProgramId`), unlike stock targets (`companyId`).
#: Counting bindings needs no note body, so the read stays PHI-clean by construction.
NOTE_TARGETS_PLURAL = "noteTargets"
NOTE_TARGET_RECORD_COLUMN = f"target{BOARD_OBJECT[0].upper()}{BOARD_OBJECT[1:]}Id"


class DemoAssertionError(AssertionError):
    """One of Demo 3's nine live assertions failed. The script exits nonzero when this is raised."""


def _check(condition: object, message: str) -> None:
    if not condition:
        raise DemoAssertionError(message)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--target",
        choices=("dev",),
        default="dev",
        help="Twenty target to run against (resolved from PULSE_TWENTY_<TARGET>_URL/_TOKEN). "
        "Only dev exists today; staging/prod would be a promotion decision, not a flag.",
    )
    parser.add_argument(
        "--card-index",
        type=int,
        default=0,
        help="Which card to drag: an index into the sorted-by-id list of seeded pending_start "
        "cards — never a name (default 0).",
    )
    return parser


def _print_receipt(step: str, body: Mapping[str, Any]) -> None:
    print(json.dumps({"step": step, **body}, default=str))


# --- Live clients --------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectedRecord:
    """One workspace record, already reduced to the fields the demo may hold (PHI posture)."""

    record_id: str
    fields: Mapping[str, Any]


class TwentyReader:
    """Every read and the one PATCH this demo issues against Twenty, paced like the seed loader."""

    def __init__(self, target: Target, client: httpx.Client | None = None, pacer: Pacer | None = None) -> None:
        self._pacer = pacer or Pacer()
        self._client = client or httpx.Client(
            base_url=target.url,
            headers={"Authorization": f"Bearer {target.token}"},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self._pacer.wait()
        response = self._client.get(path, params=params)
        _check(response.status_code < 400, f"GET {path} answered {response.status_code}")
        return response.json()

    def metadata_records(self, collection: str) -> list[dict[str, Any]]:
        """One metadata listing, every page — `twenty_deploy._list_all`'s verified surface."""
        records: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, str] = {"limit": "200"}
            if cursor is not None:
                params["starting_after"] = cursor
            body = self._get(f"{METADATA_ROOT}/{collection}", params=params)
            records.extend(body.get("data", ()))
            page = body.get("pageInfo") or {}
            cursor = page.get("endCursor")
            if not page.get("hasNextPage") or cursor is None:
                return records

    def graphql(self, path: str, query: str) -> dict[str, Any]:
        self._pacer.wait()
        response = self._client.post(path, json={"query": query})
        _check(response.status_code < 400, f"POST {path} answered {response.status_code}")
        body = response.json()
        _check(
            not body.get("errors"),
            f"POST {path} answered a GraphQL error ({len(body.get('errors') or ())} entries; bodies withheld)",
        )
        return body.get("data") or {}

    def list_projected(self, plural: str, keep: Sequence[str]) -> tuple[ProjectedRecord, ...]:
        """Every record of one object, reduced to `keep` at the response boundary."""
        records: list[ProjectedRecord] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 60}
            if cursor is not None:
                params["starting_after"] = cursor
            body = self._get(f"/rest/{plural}", params=params)
            for record in body.get("data", {}).get(plural, ()):
                records.append(
                    ProjectedRecord(
                        record_id=str(record["id"]),
                        fields={name: record.get(name) for name in keep},
                    )
                )
            page = body.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                return tuple(records)
            cursor = str(page["endCursor"])

    def get_projected(self, plural: str, record_id: str, keep: Sequence[str], singular: str) -> ProjectedRecord:
        body = self._get(f"/rest/{plural}/{record_id}")
        record = body.get("data", {}).get(singular) or {}
        _check(record.get("id") is not None, f"read-back of {singular}:{record_id} carried no record")
        return ProjectedRecord(
            record_id=str(record["id"]),
            fields={name: record.get(name) for name in keep},
        )

    def patch(self, plural: str, record_id: str, payload: Mapping[str, Any]) -> None:
        self._pacer.wait()
        response = self._client.patch(f"/rest/{plural}/{record_id}", json=dict(payload))
        _check(response.status_code < 400, f"PATCH /rest/{plural}/{record_id} answered {response.status_code}")

    def count_comments(self, record_id: str) -> int:
        """How many rejection notes are bound to one record — `noteTarget` bindings matched on
        the flat relation column. Note bodies are never fetched."""
        count = 0
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 60}
            if cursor is not None:
                params["starting_after"] = cursor
            body = self._get(f"/rest/{NOTE_TARGETS_PLURAL}", params=params)
            for record in body.get("data", {}).get(NOTE_TARGETS_PLURAL, ()):
                if record.get(NOTE_TARGET_RECORD_COLUMN) == record_id:
                    count += 1
            page = body.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                return count
            cursor = str(page["endCursor"])


class LedgerDeliverer:
    """Signs and delivers webhook bodies to the served ledger API — Twenty's wire format exactly."""

    def __init__(self, base_url: str, secret: str, client: httpx.Client | None = None) -> None:
        self._secret = secret
        self._client = client or httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT_SECONDS)

    def deliver(self, payload: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload).encode()
        timestamp = str(int(time.time() * 1000))
        headers = {
            TIMESTAMP_HEADER: timestamp,
            SIGNATURE_HEADER: sign(self._secret, timestamp, body),
            NONCE_HEADER: secrets.token_hex(16),
            "Content-Type": "application/json",
        }
        response = self._client.post(TWENTY_WEBHOOK_PATH, content=body, headers=headers)
        return response.status_code, response.json()


# --- Vocabulary helpers ---------------------------------------------------------------------------


def _decode_state(wire_value: object) -> str | None:
    """The catalog `enrollment` state behind one wire SELECT token, or None for a stranger."""
    if not isinstance(wire_value, str):
        return None
    for state in TRANSITIONS[SUBJECT_TYPE]:
        if encode_option_value(state) == wire_value:
            return state
    return None


def _legal_target(state: str) -> str:
    """The next column this demo drags to: the first non-`ended` legal move, sorted for determinism.

    `ended` is absorbing — dragging there once would strand the card for every later run — so the
    demo walks the `pending_start → active ⇄ on_hold` cycle instead.
    """
    candidates = sorted(TRANSITIONS[SUBJECT_TYPE][state] - {"ended"})
    _check(candidates, f"state {state!r} has no non-ended legal move — rerun with another --card-index")
    return candidates[0]


def _illegal_target(state: str) -> str:
    """A column the catalog forbids from `state` — never the state itself, which is a non-drag."""
    candidates = sorted(set(TRANSITIONS[SUBJECT_TYPE]) - TRANSITIONS[SUBJECT_TYPE][state] - {state})
    _check(candidates, f"state {state!r} has no illegal move to demonstrate")
    return candidates[0]


def _canonical_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    _check(parsed.tzinfo is not None, f"timestamp {value!r} carries no zone")
    return parsed.astimezone(UTC)


def _wire_timestamp(value: datetime) -> str:
    """A datetime as Twenty stamps it: UTC, millisecond precision, Z suffix."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def _drag_payload(card: ProjectedRecord, wire_state: str, updated_at: str) -> dict[str, Any]:
    """A webhook body in the captured v2.30 shape, carrying only the fields the mapping reads."""
    return {
        "eventName": MAPPED_OPERATION,
        "objectMetadata": {"nameSingular": BOARD_OBJECT},
        "record": {
            "id": card.record_id,
            "canonicalPatientId": card.fields.get("canonicalPatientId"),
            "programCode": card.fields.get("programCode"),
            STATUS_FIELD: wire_state,
            "updatedAt": updated_at,
        },
        "updatedFields": [STATUS_FIELD],
    }


# --- The nine assertions --------------------------------------------------------------------------


def step_uid_round_trip(twenty: TwentyReader, uid_map: dict[str, str]) -> tuple[str, str]:
    """1/9: the live object and status field carry the minted universalIdentifiers (F1, held).

    Returns the object's and the status field's internal metadata ids — assertion 2 keys on both,
    because a live view record names its object and its group-by field by internal id, and carries
    no `universalIdentifier` of its own to match on.
    """
    objects = {str(record.get("nameSingular")): record for record in twenty.metadata_records("objects")}
    _check(BOARD_OBJECT in objects, f"object {BOARD_OBJECT!r} is not in the workspace")
    live_object = objects[BOARD_OBJECT]
    expected_object_uid = require_uid(uid_map, BOARD_OBJECT)
    _check(
        str(live_object.get("universalIdentifier")) == expected_object_uid,
        f"object {BOARD_OBJECT!r} universalIdentifier did not round-trip: "
        f"live {live_object.get('universalIdentifier')!r} != minted {expected_object_uid!r}",
    )

    object_id = str(live_object["id"])
    fields = [
        record
        for record in twenty.metadata_records("fields")
        if str(record.get("objectMetadataId")) == object_id and str(record.get("name")) == STATUS_FIELD
    ]
    _check(len(fields) == 1, f"expected exactly one live {BOARD_OBJECT}.{STATUS_FIELD} field, found {len(fields)}")
    expected_field_uid = require_uid(uid_map, f"{BOARD_OBJECT}.{STATUS_FIELD}")
    _check(
        str(fields[0].get("universalIdentifier")) == expected_field_uid,
        f"field {BOARD_OBJECT}.{STATUS_FIELD} universalIdentifier did not round-trip: "
        f"live {fields[0].get('universalIdentifier')!r} != minted {expected_field_uid!r}",
    )
    _print_receipt("uid_round_trip", {"object": BOARD_OBJECT, "field": STATUS_FIELD, "round_tripped": True})
    return object_id, str(fields[0]["id"])


def match_board_views(views: Sequence[Mapping[str, Any]], object_metadata_id: str) -> list[Mapping[str, Any]]:
    """Every live view that is this board: the board object, KANBAN, and the app view's name.

    The three together stand in for the UID match the live `View` type cannot support — object id
    alone would also take the table view, and name alone is not scoped to an object.
    """
    return [
        view
        for view in views
        if str(view.get("objectMetadataId")) == object_metadata_id
        and str(view.get("type")) == "KANBAN"
        and str(view.get("name")) == VIEW_NAME
    ]


def step_view_shape(twenty: TwentyReader, object_metadata_id: str, status_field_id: str) -> dict[str, Any]:
    """2/9: the board exists, is KANBAN, and groups on the status field. Returns the view record."""
    views = twenty.graphql(GRAPHQL_PATH, VIEWS_QUERY).get("getViews") or []
    matches = match_board_views(views, object_metadata_id)
    _check(len(matches) == 1, f"expected exactly one live view for {VIEW_KEY!r}, found {len(matches)}")
    # The KANBAN check lives in the match itself: the type is part of what identifies this board
    # now that no UID does.
    view = matches[0]
    _check(
        str(view.get("mainGroupByFieldMetadataId")) == status_field_id,
        f"view {VIEW_KEY!r} groups on field id {view.get('mainGroupByFieldMetadataId')!r}, "
        f"not the live {BOARD_OBJECT}.{STATUS_FIELD} field",
    )
    _print_receipt("view_shape", {"view": VIEW_KEY, "type": "KANBAN", "groups_on": f"{BOARD_OBJECT}.{STATUS_FIELD}"})
    return dict(view)


def step_column_parity(view: Mapping[str, Any]) -> None:
    """3/9: the board's columns are exactly the catalog's enrollment states, encoded."""
    live_columns = {
        str(group.get("fieldValue")) for group in view.get("viewGroups") or () if isinstance(group, Mapping)
    }
    catalog_columns = {encode_option_value(state) for state in TRANSITIONS[SUBJECT_TYPE]}
    _check(
        live_columns == catalog_columns,
        f"column parity failed: live-only {sorted(live_columns - catalog_columns)}, "
        f"catalog-only {sorted(catalog_columns - live_columns)}",
    )
    _print_receipt("column_parity", {"columns": sorted(catalog_columns)})


def step_seed_counts(twenty: TwentyReader, live_by_object: dict[str, tuple[ProjectedRecord, ...]]) -> dict[str, Any]:
    """4/9: every projection record is present in the workspace, matched by natural key.

    Returns the projection so later steps reuse the verified load. Counts compare presence, not
    field equality — a prior demo run has legitimately dragged a seeded card since it landed.
    """
    projection = load_projection(SEED_PATH)
    for obj in SEED_OBJECTS:
        live_by_object[obj.plural] = twenty.list_projected(obj.plural, PROJECTED_FIELDS[obj.plural])
        wanted = {natural_key(obj, record["fields"]) for record in projection.records[obj.plural]}
        present = {
            natural_key(obj, record.fields)
            for record in live_by_object[obj.plural]
            if all(record.fields.get(name) for name in obj.key_fields)
        }
        missing = wanted - present
        _check(
            not missing,
            f"{obj.plural}: {len(missing)} of {len(wanted)} seeded records are missing from the workspace",
        )
    counts = {obj.plural: len(projection.records[obj.plural]) for obj in SEED_OBJECTS}
    _print_receipt("seed_counts", {"present": counts, "checksum": projection.checksum})
    return {"projection": projection}


def step_as_of_stamps(live_by_object: Mapping[str, tuple[ProjectedRecord, ...]]) -> None:
    """5/9: every seeded board record carries non-null status as-of stamps — first drags resolve."""
    unstamped = 0
    for plural, stamps in BOARD_AS_OF_FIELDS.items():
        for record in live_by_object[plural]:
            if any(not record.fields.get(stamp) for stamp in stamps):
                unstamped += 1
    _check(unstamped == 0, f"{unstamped} board records carry a null status as-of stamp")
    _print_receipt(
        "as_of_stamps",
        {"checked": len(live_by_object[BOARD_OBJECT_PLURAL]), "stamps": list(BOARD_AS_OF_FIELDS[BOARD_OBJECT_PLURAL])},
    )


def step_one_webhook(twenty: TwentyReader) -> None:
    """6/9: exactly one webhook, scoped to exactly the mapped operation — never the wildcard."""
    webhooks = twenty.graphql(GRAPHQL_PATH, WEBHOOKS_QUERY).get("webhooks") or []
    mapped = [hook for hook in webhooks if MAPPED_OPERATION in (hook.get("operations") or ())]
    _check(len(mapped) == 1, f"expected exactly one webhook for {MAPPED_OPERATION!r}, found {len(mapped)}")
    _check(
        list(mapped[0].get("operations") or ()) == [MAPPED_OPERATION],
        f"the webhook's operations are {mapped[0].get('operations')!r}, expected exactly [{MAPPED_OPERATION!r}]",
    )
    _print_receipt("one_webhook", {"operation": MAPPED_OPERATION, "count": 1})


def _select_card(
    live_boards: Sequence[ProjectedRecord], projection_records: Sequence[Mapping[str, Any]], index: int
) -> tuple[ProjectedRecord, Mapping[str, Any]]:
    """The drag target: `index` into the sorted-by-id list of cards seeded at `pending_start`.

    Selection is by id order and index only — never by name — and is stable across runs because it
    keys on the committed projection's states, not the live columns the demo itself moves.
    """
    seeded_pending = {
        natural_key(SEED_OBJECTS[-1], record["fields"])
        for record in projection_records
        if record["fields"].get(STATUS_FIELD) == "pending_start"
    }
    candidates = sorted(
        (record for record in live_boards if natural_key(SEED_OBJECTS[-1], record.fields) in seeded_pending),
        key=lambda record: record.record_id,
    )
    _check(
        0 <= index < len(candidates),
        f"--card-index {index} is out of range: {len(candidates)} seeded pending_start cards exist",
    )
    card = candidates[index]
    matched = next(
        record
        for record in projection_records
        if natural_key(SEED_OBJECTS[-1], record["fields"]) == natural_key(SEED_OBJECTS[-1], card.fields)
    )
    return card, matched


def _drag_delivery_confirms_causation(body: Mapping[str, Any]) -> bool:
    """Whether `step_legal_drag`'s own delivery is an acceptable outcome for causing the drag.

    Any of three outcomes passes: this delivery committed it, this delivery replayed an earlier
    attempt of its own, or Twenty's real webhook already committed it and this delivery is exactly
    what echo suppression (task 2.4) is built to answer with — `noop reason=echo_of_record`. This
    call never reads the commit's own properties (`step_replay`'s probe does that instead); it only
    has to be satisfied that an event now exists for the drag before the probe reads it back.
    """
    disposition = body.get("disposition")
    if disposition in ("committed", "replayed"):
        return True
    return disposition == "noop" and body.get("reason") == "echo_of_record"


def step_legal_drag(
    twenty: TwentyReader,
    ledger: LedgerDeliverer,
    card: ProjectedRecord,
    seeded_fields: Mapping[str, Any],
) -> tuple[ProjectedRecord, str, str, str]:
    """7/9: a legal drag commits, driven through Twenty's REST API.

    Returns the moved record, its own `updatedAt` stamp, the state dragged *from*, and the state
    dragged *to* — everything `step_replay`'s probe needs to prove `effective_at` and
    no-second-event against the real committed event (module docstring: why steps 7/8 changed).
    """
    # Genesis alignment (see module docstring): fixed logical time -> first run commits the
    # subject's entry state, every later run replays with no rejection note and no second event.
    genesis_payload = _drag_payload(
        card,
        wire_state=encode_option_value("pending_start"),
        updated_at=str(seeded_fields["lifecycleStatusAsOf"]),
    )
    status, body = ledger.deliver(genesis_payload)
    _print_receipt("genesis_alignment", {"disposition": body.get("disposition"), "status": status})
    _check(status == 200, f"genesis alignment expected 200, got {status}")
    _check(
        body.get("disposition") in ("committed", "replayed"),
        f"genesis alignment expected committed or replayed, got {body.get('disposition')!r}",
    )

    current = _decode_state(card.fields.get(STATUS_FIELD))
    if current is None or current == "ended":
        msg = (
            f"card {card.record_id} sits in column {card.fields.get(STATUS_FIELD)!r} — not a "
            "draggable catalog state; rerun with another --card-index"
        )
        raise DemoAssertionError(msg)
    target_state = _legal_target(current)

    twenty.patch(BOARD_OBJECT_PLURAL, card.record_id, {STATUS_FIELD: encode_option_value(target_state)})
    moved = twenty.get_projected(
        BOARD_OBJECT_PLURAL, card.record_id, PROJECTED_FIELDS[BOARD_OBJECT_PLURAL], BOARD_OBJECT
    )
    stamp = moved.fields.get("updatedAt")
    if not isinstance(stamp, str) or not stamp:
        msg = "the moved record carried no updatedAt stamp"
        raise DemoAssertionError(msg)
    updated_at = stamp

    drag_payload = _drag_payload(moved, wire_state=encode_option_value(target_state), updated_at=updated_at)
    status, body = ledger.deliver(drag_payload)
    _print_receipt("legal_drag", {k: body.get(k) for k in ("disposition", "reason", "event_id")} | {"status": status})
    _check(status == 200, f"legal drag expected 200, got {status}")
    _check(
        _drag_delivery_confirms_causation(body),
        f"legal drag expected committed, replayed, or an echo_of_record noop, "
        f"got {body.get('disposition')!r}/{body.get('reason')!r}",
    )
    return moved, updated_at, current, target_state


def _replay_probe_payload(card: ProjectedRecord, previous_state: str, updated_at: str) -> dict[str, Any]:
    """The follow-up delivery `step_replay` uses to prove D16 without echo suppression eating it.

    Naming `previous_state` — the state the card was dragged *from*, never equal to the state it
    was dragged to — as this delivery's target cannot be an echo (module docstring: why steps 7/8
    changed), so the only thing left to answer it is a replay of the drag's own idempotency key:
    the same subject, program, and `updated_at` the committing drag carried.
    """
    return _drag_payload(card, wire_state=encode_option_value(previous_state), updated_at=updated_at)


def step_replay(
    ledger: LedgerDeliverer,
    card: ProjectedRecord,
    previous_state: str,
    updated_at: str,
) -> None:
    """8/9: a replay probe proves `effective_at` is the record's own stamp and that a redelivery
    of the drag's idempotency key produces no second event — both against the real committed
    event, whoever committed it (module docstring: why steps 7/8 changed).
    """
    probe = _replay_probe_payload(card, previous_state, updated_at)
    status, body = ledger.deliver(probe)
    _print_receipt("replay_probe", {k: body.get(k) for k in ("disposition", "event_id")} | {"status": status})
    _check(status == 200, f"replay probe expected 200, got {status}")
    # `echo_of_record` is not an acceptable answer here even though it is a `noop`: the probe is
    # built so it cannot be an echo of the state of record (it names the *previous* state), so
    # anything other than `replayed` means the idempotency key this probe carries was never
    # claimed — the drag never committed, or committed under a different key than expected.
    _check(
        body.get("disposition") == "replayed",
        f"replay probe expected disposition 'replayed', got {body.get('disposition')!r} — "
        "no committed event was found for this drag's idempotency key",
    )
    event_id = body.get("event_id")
    _check(event_id is not None, "the replay probe carried no event id")
    state = body.get("state") or {}
    effective_at = state.get("effective_at")
    _check(effective_at is not None, "the replay probe carried no effective_at")
    _check(
        _canonical_timestamp(str(effective_at)) == _canonical_timestamp(updated_at),
        f"effective_at {effective_at!r} is not the record stamp {updated_at!r} — a wall-clock time leaked in",
    )
    _print_receipt("effective_at", {"effective_at": str(effective_at), "record_updated_at": updated_at})


def step_illegal_drag(
    twenty: TwentyReader,
    ledger: LedgerDeliverer,
    card: ProjectedRecord,
    committed_state: str,
) -> None:
    """9/9: an illegal drag is 200 `rejected`, binds exactly one rejection note, changes nothing.

    Delivered directly, never PATCHed into Twenty: the card must not actually move, so "the state
    of record unchanged" is checkable on both sides — the ledger rejected (no event id), and the
    card still sits in the legally dragged column.
    """
    card_ref = f"{BOARD_OBJECT}:{card.record_id}"
    comments_before = twenty.count_comments(card.record_id)

    before = twenty.get_projected(
        BOARD_OBJECT_PLURAL, card.record_id, PROJECTED_FIELDS[BOARD_OBJECT_PLURAL], BOARD_OBJECT
    )
    updated_at = str(before.fields.get("updatedAt"))
    illegal_state = _illegal_target(committed_state)
    # A later logical time than the legal drag's, so the idempotency pre-check cannot swallow the
    # rejection as a replay of the committed event.
    bumped = _wire_timestamp(_canonical_timestamp(updated_at) + timedelta(seconds=1))
    payload = _drag_payload(before, wire_state=encode_option_value(illegal_state), updated_at=bumped)

    status, body = ledger.deliver(payload)
    _print_receipt(
        "illegal_drag",
        {k: body.get(k) for k in ("disposition", "from_state", "to_state", "reason", "catalog_version")}
        | {"status": status},
    )
    _check(status == 200, f"illegal drag expected 200 (a rejection receipt, not an error status), got {status}")
    _check(body.get("disposition") == "rejected", f"expected disposition 'rejected', got {body.get('disposition')!r}")
    _check(
        body.get("from_state") == committed_state,
        f"rejection departs {body.get('from_state')!r}, expected {committed_state!r}",
    )
    _check(
        body.get("to_state") == illegal_state,
        f"rejection names to_state {body.get('to_state')!r}, expected {illegal_state!r}",
    )
    _check(bool(body.get("reason")), "rejection receipt carried no catalog reason")
    _check("event_id" not in body, "a rejected drag carried an event id — something committed")

    comments_after = twenty.count_comments(card.record_id)
    _check(
        comments_after == comments_before + 1,
        f"expected exactly one new rejection note on the card, found {comments_after - comments_before}",
    )

    after = twenty.get_projected(
        BOARD_OBJECT_PLURAL, card.record_id, PROJECTED_FIELDS[BOARD_OBJECT_PLURAL], BOARD_OBJECT
    )
    _check(
        after.fields.get(STATUS_FIELD) == encode_option_value(committed_state),
        f"the card moved to {after.fields.get(STATUS_FIELD)!r} — the state of record changed on a rejection",
    )
    _print_receipt(
        "state_unchanged",
        {"card_ref": card_ref, "state": committed_state, "new_notes": comments_after - comments_before},
    )


# --- Entry point ----------------------------------------------------------------------------------


def _resolve_ledger(env: Mapping[str, str]) -> tuple[str, str]:
    missing = [name for name in (LEDGER_URL_ENV, TWENTY_WEBHOOK_SECRET_ENV) if not env.get(name)]
    if missing:
        msg = f"the ledger API is not configured — set: {', '.join(missing)}"
        raise DeployError(msg)
    return env[LEDGER_URL_ENV], env[TWENTY_WEBHOOK_SECRET_ENV]


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    environment = os.environ if env is None else env

    print("=== Demo 3: the live kanban round trip ===")
    try:
        target = resolve_target(args.target, environment)
        ledger_url, secret = _resolve_ledger(environment)
    except DeployError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1

    twenty = TwentyReader(target)
    ledger = LedgerDeliverer(ledger_url, secret)
    uid_map = load_uid_map()
    live_by_object: dict[str, tuple[ProjectedRecord, ...]] = {}

    try:
        print("\n[1/9] universalIdentifier round-trips on the live object and field")
        object_id, status_field_id = step_uid_round_trip(twenty, uid_map)

        print("\n[2/9] the lifecycle board exists, is KANBAN, and groups on the status field")
        view = step_view_shape(twenty, object_id, status_field_id)

        print("\n[3/9] the board's columns are exactly the catalog's states")
        step_column_parity(view)

        print("\n[4/9] every seeded record is present in the workspace")
        seed = step_seed_counts(twenty, live_by_object)

        print("\n[5/9] every seeded board record carries non-null as-of stamps")
        step_as_of_stamps(live_by_object)

        print("\n[6/9] exactly one webhook, scoped to the mapped operation")
        step_one_webhook(twenty)

        card, seeded = _select_card(
            live_by_object[BOARD_OBJECT_PLURAL],
            seed["projection"].records[BOARD_OBJECT_PLURAL],
            args.card_index,
        )
        print(f"\n[7/9] a legal drag commits, driven through Twenty (card {card.record_id})")
        moved, updated_at, previous_state, committed_state = step_legal_drag(twenty, ledger, card, seeded["fields"])

        print("\n[8/9] a replay probe proves the record's own stamp and no second event")
        step_replay(ledger, moved, previous_state, updated_at)

        print("\n[9/9] an illegal drag is rejected with one rejection note and no state change")
        step_illegal_drag(twenty, ledger, card, committed_state)
    except DemoAssertionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("\n=== Demo 3: all nine live assertions passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
