"""Replay a validated Twenty artifact against one target (pulse-app-scaffold 3.3).

The only path by which the Metadata API artifact reaches an instance, and dumb by design
(design Decision 4): it reads `packages/twenty-app/artifact/operations.json` and a target name,
and carries zero generation logic. Promotion dev → staging → prod is the *same file*, next
target — which is what makes the receipt's artifact checksum a cross-environment identity check
rather than a hope.

Four properties, each of which a test pins:

- **Validate before apply.** Every operation is gated behind `twenty_validate`. A schema failure,
  an unparseable file, or (for the committed artifact) any 2.3 finding exits nonzero naming the
  finding, before the target is even read.
- **Idempotent, keyed on `universalIdentifier`.** Create when the key is absent, update when the
  payload drifted, no-op when identical. Roles carry no identifier in the artifact, so their key
  is `role:<name>` — also stable, also named in the artifact.
- **Never delete.** Not "we do not call delete" but "there is no verb to call": `VERBS` is
  `("create", "update")` and the transport exposes nothing else, so a key present on the target
  and absent from the artifact is left alone by construction.
- **Receipts carry names, counts, and the checksum — never workspace data.** `TransportError`
  holds a status code and has no field for a body, so no error path can echo a response that on a
  live workspace would carry record data. Credentials are equally absent: `Target.__repr__` hides
  the token.

URL and credential resolve from the environment (`PULSE_TWENTY_<TARGET>_URL` /
`PULSE_TWENTY_<TARGET>_TOKEN`), never from code and never from the artifact. Missing ones are an
error naming the variables, never a silent no-op — the `catalog_release_cli` posture.

The request/response shapes below are pinned against the DNA-909 provisioning receipt
(2026-08-16, v2.30): the metadata REST surface serves `objects` and `fields` only — relations
apply as RELATION-type field payloads on the fields surface, roles through the `/metadata`
GraphQL — and `universalIdentifier` round-trips (F1 positive). Every test drives a scripted
transport under disabled sockets; wave 3's read-back (task 3.1) is the remaining ground truth for
the exact body shapes, and a drift there changes this module's payload construction and nothing
else.

Run: uv run python -m pulse_core.twenty_deploy --target dev [--dry-run]   (task twenty:deploy)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

from pulse_core.catalog_gen import load_catalog
from pulse_core.twenty_metadata import ARTIFACT_PATH
from pulse_core.twenty_model import TWENTY_MODEL, load_uid_map
from pulse_core.twenty_validate import check_schema, validate

#: The targets a promotion walks, in order. A name outside this tuple is an error rather than an
#: ad-hoc environment: an unlisted target has no reviewed credential pair.
TARGET_NAMES = ("dev", "staging", "prod")

#: The only two things this step does to a target. Deletion is not omitted from a longer list —
#: it is absent from the vocabulary, which is what makes "never deletes" structural.
VERBS: tuple[Literal["create"], Literal["update"]] = ("create", "update")

Verb = Literal["create", "update"]

#: Path prefix for the Metadata REST API, and the collection each REST-served kind addresses.
#: Per the DNA-909 provisioning receipt (2026-08-16), v2.30 serves exactly two collections here:
#: `objects` and `fields` — `/rest/metadata/relations` and `/rest/metadata/roles` do not exist
#: (the router parses those segments as object ids and answers 400). A relation is a
#: RELATION-type field payload on the fields surface; roles have no REST surface at all and are
#: deliberately absent from this mapping — they apply through the metadata GraphQL below.
METADATA_ROOT = "/rest/metadata"
COLLECTIONS = {
    "createObject": "objects",
    "createField": "fields",
    "createRelation": "fields",
}

#: The metadata GraphQL endpoint — the only surface that serves roles on v2.30.
GRAPHQL_PATH = "/metadata"

#: The role read and writes, pinned as our shape until 3.1's live read-back. Selections mirror the
#: artifact's role payload so drift comparison sees the keys it plans on.
ROLES_QUERY = (
    "query DeployReadRoles { getRoles { id name label description"
    " objectPermissions { objectNameSingular canRead canCreate canUpdate canDelete }"
    " fieldPermissions { objectNameSingular fieldName canRead canUpdate } } }"
)
CREATE_ROLE_MUTATION = (
    "mutation DeployCreateRole($input: CreateRoleInput!) { createOneRole(createRoleInput: $input) { id } }"
)
UPDATE_ROLE_MUTATION = (
    "mutation DeployUpdateRole($id: UUID!, $update: UpdateRolePayload!)"
    " { updateOneRole(updateRoleInput: {id: $id, update: $update}) { id } }"
)

DEFAULT_TIMEOUT_SECONDS = 30.0


class DeployError(RuntimeError):
    """A refusal before anything was sent: bad artifact, unknown target, missing credential."""


class TransportError(RuntimeError):
    """The target rejected one operation.

    Carries the status code and nothing else *on purpose*. A live workspace answers a failed
    metadata write with a body that can quote record data, and a receipt is a thing people attach
    to tickets — so the body is dropped where it is read, not filtered where it is printed.
    """

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"the target rejected the operation with status {status}")


@dataclass(frozen=True)
class Target:
    """One instance: where it is and how to authenticate. Both from the environment."""

    name: str
    url: str
    token: str = field(repr=False)


@dataclass(frozen=True)
class RemoteRecord:
    """One record as the target reports it: its server-side id, and the payload we compare."""

    record_id: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class PlanItem:
    """One artifact operation resolved against the target's state."""

    key: str
    kind: str
    name: str
    payload: Mapping[str, Any]
    record_id: str | None = None
    verb: Verb | None = None


class Transport(Protocol):
    """The Metadata API boundary — the one place tests fake (design Decision 7)."""

    def read_state(self) -> dict[str, RemoteRecord]: ...

    def send(self, verb: Verb, item: PlanItem) -> None: ...


# --- Artifact ----------------------------------------------------------------------------------


def artifact_checksum(path: Path) -> str:
    """The applied artifact's identity, recorded in every receipt: sha256 of the file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validation_findings(path: Path) -> tuple[str, ...]:
    """Every reason this artifact must not be applied, in reporting order.

    The committed artifact gets the full 2.3 suite — schema, staleness, UID map, options, TS
    parity — because for that file every check is meaningful. Any other path (a promotion
    candidate copied out of a release) gets the schema check, which is the half that describes
    what this module is about to send; the rest compare the file against *this tree's* inputs and
    would report drift that says nothing about the artifact's validity.
    """
    try:
        artifact = json.loads(path.read_text())
    except FileNotFoundError:
        return (f"{path} is missing",)
    except json.JSONDecodeError as error:
        return (f"{path.name} is not valid JSON: {error}",)
    if path == ARTIFACT_PATH:
        return validate(TWENTY_MODEL, load_catalog(), load_uid_map())
    return check_schema(artifact)


def operation_key(operation: Mapping[str, Any]) -> str:
    """The identity an operation is applied under — stable across syncs and environments."""
    if (uid := operation.get("universalIdentifier")) is not None:
        return str(uid)
    if operation["operation"] == "createRelation":
        return str(operation["from"]["universalIdentifier"])
    return f"role:{operation['name']}"


def operation_name(operation: Mapping[str, Any]) -> str:
    """What the receipt calls this operation: its kind and the thing it names, never its data."""
    kind = operation["operation"]
    if kind == "createObject":
        return f"createObject {operation['nameSingular']}"
    if kind == "createField":
        return f"createField {operation['objectNameSingular']}.{operation['name']}"
    if kind == "createRelation":
        end = operation["from"]
        return f"createRelation {end['objectNameSingular']}.{end['fieldName']}"
    return f"createRole {operation['name']}"


def relation_field_payload(operation: Mapping[str, Any]) -> dict[str, Any]:
    """A relation operation as the fields surface takes it: a RELATION-type field on the from side.

    v2.30 has no relations collection (DNA-909 receipt) — the from-side field carries the whole
    relation, target end included, under the `relation` key. The key stays the from side's
    `universalIdentifier`, so idempotence is unchanged: the field this payload creates reads back
    from the fields listing under the same identifier.
    """
    from_end = operation["from"]
    to_end = operation["to"]
    payload = {
        "universalIdentifier": from_end["universalIdentifier"],
        "objectNameSingular": from_end["objectNameSingular"],
        "name": from_end["fieldName"],
        "label": from_end["label"],
        "type": "RELATION",
        "relation": {
            "type": operation["type"],
            "targetUniversalIdentifier": to_end["universalIdentifier"],
            "targetObjectNameSingular": to_end["objectNameSingular"],
            "targetFieldName": to_end["fieldName"],
            "targetFieldLabel": to_end["label"],
        },
    }
    if "isNullable" in from_end:
        payload["isNullable"] = from_end["isNullable"]
    return payload


def desired_payload(operation: Mapping[str, Any]) -> dict[str, Any]:
    """The operation as a request body: everything except the discriminator we route on.

    Relations are the one reshape: the artifact keeps its two-ended `createRelation` form, and the
    body it plans and sends is the RELATION field payload the v2.30 fields surface actually takes.
    """
    if operation["operation"] == "createRelation":
        return relation_field_payload(operation)
    return {key: value for key, value in operation.items() if key != "operation"}


# --- Plan --------------------------------------------------------------------------------------


def plan(operations: tuple[Mapping[str, Any], ...], state: Mapping[str, RemoteRecord]) -> tuple[PlanItem, ...]:
    """Resolve every artifact operation against the target's state, in artifact order.

    Drift is *any* key the artifact asks for whose remote value differs. Keys the target reports
    but the artifact does not name are ignored: server-side defaults are not drift, and the
    artifact is not a description of the whole record.
    """
    items = []
    for operation in operations:
        key = operation_key(operation)
        payload = desired_payload(operation)
        current = state.get(key)
        if current is None:
            verb: Verb | None = "create"
        elif any(current.payload.get(name) != value for name, value in payload.items()):
            verb = "update"
        else:
            verb = None
        items.append(
            PlanItem(
                key=key,
                kind=operation["operation"],
                name=operation_name(operation),
                payload=payload,
                record_id=None if current is None else current.record_id,
                verb=verb,
            )
        )
    return tuple(items)


def plan_lines(items: tuple[PlanItem, ...]) -> tuple[str, ...]:
    """The plan a human reads, and what the receipt records: `<verb> <name>`, artifact order."""
    return tuple(f"{item.verb or 'noop'} {item.name}" for item in items)


# --- Receipt -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Receipt:
    """What a run is worth attaching: which artifact went where, and what it did.

    Names, counts, and a checksum. No payloads, no response bodies, no credential.
    """

    target: str
    artifact: str
    checksum: str
    dry_run: bool
    counts: Mapping[str, int]
    operations: tuple[str, ...]
    failure: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "artifact": self.artifact,
            "checksum": self.checksum,
            "dryRun": self.dry_run,
            "counts": dict(self.counts),
            "operations": list(self.operations),
            "failure": self.failure,
        }


def _counts(items: tuple[PlanItem, ...], applied: int) -> dict[str, int]:
    """Planned creates/updates capped at what actually went out, plus the no-ops."""
    mutating = [item for item in items if item.verb is not None]
    done = mutating[:applied]
    return {
        "create": sum(1 for item in done if item.verb == "create"),
        "update": sum(1 for item in done if item.verb == "update"),
        "noop": sum(1 for item in items if item.verb is None),
    }


# --- Target resolution -------------------------------------------------------------------------


def env_var_names(target: str) -> tuple[str, str]:
    """The URL and credential variables a target reads, in that order."""
    return (f"PULSE_TWENTY_{target.upper()}_URL", f"PULSE_TWENTY_{target.upper()}_TOKEN")


def resolve_target(target: str, env: Mapping[str, str]) -> Target:
    """Map a target name to URL and credential from the environment — never from code.

    An empty value counts as missing: an unset secret reaches a job as an empty string, and
    treating that as present would apply with garbage.
    """
    if target not in TARGET_NAMES:
        msg = f"unknown target {target!r} — expected one of {', '.join(TARGET_NAMES)}"
        raise DeployError(msg)
    url_var, token_var = env_var_names(target)
    missing = [name for name in (url_var, token_var) if not env.get(name)]
    if missing:
        msg = f"target {target!r} is not configured — set: {', '.join(missing)}"
        raise DeployError(msg)
    return Target(name=target, url=env[url_var], token=env[token_var])


# --- Transport ---------------------------------------------------------------------------------


class MetadataApiTransport:
    """The metadata surfaces v2.30 actually serves: two REST collections and the GraphQL roles.

    Two verbs and a read, same as before the DNA-909 receipt — only the routing changed. Objects
    and fields (relations included, as RELATION-type fields) go over `/rest/metadata`; roles go
    over the `/metadata` GraphQL, because no REST roles collection exists. Response bodies are
    consumed for the `id`/`universalIdentifier` pairs they carry on the read path, and dropped
    entirely on every failure path (see `TransportError`) — a GraphQL rejection answers 200 with
    an `errors` list, and that body is dropped the same way.
    """

    def __init__(self, target: Target, client: httpx.Client | None = None) -> None:
        self._target = target
        self._client = client or httpx.Client(
            base_url=target.url,
            headers={"Authorization": f"Bearer {target.token}"},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )

    def _collection_url(self, kind: str, record_id: str | None = None) -> str:
        collection = f"{METADATA_ROOT}/{COLLECTIONS[kind]}"
        return collection if record_id is None else f"{collection}/{record_id}"

    def _graphql(self, query: str, variables: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """One GraphQL call. An `errors` body is a rejection: pinned as status 400, body dropped."""
        response = self._client.post(GRAPHQL_PATH, json={"query": query, "variables": dict(variables or {})})
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise TransportError(response.status_code)
        body = response.json()
        if body.get("errors"):
            raise TransportError(httpx.codes.BAD_REQUEST)
        data: dict[str, Any] = body.get("data") or {}
        return data

    def read_state(self) -> dict[str, RemoteRecord]:
        """Every record the target already carries, indexed by the key the plan is computed on.

        Exactly three requests: the two REST listings that exist (`objects`, `fields` — a
        RELATION-type field in the listing *is* a relation's state), and the roles GraphQL query.
        Never `/rest/metadata/relations` or `/rest/metadata/roles` — v2.30 answers those with 400.
        """
        state: dict[str, RemoteRecord] = {}
        for collection in sorted(set(COLLECTIONS.values())):
            response = self._client.get(f"{METADATA_ROOT}/{collection}")
            if response.status_code >= httpx.codes.BAD_REQUEST:
                raise TransportError(response.status_code)
            for record in response.json().get("data", ()):
                payload = {name: value for name, value in record.items() if name != "id"}
                key = str(record["universalIdentifier"])
                state[key] = RemoteRecord(record_id=str(record["id"]), payload=payload)
        for role in self._graphql(ROLES_QUERY).get("getRoles") or ():
            payload = {name: value for name, value in role.items() if name != "id"}
            state[f"role:{role['name']}"] = RemoteRecord(record_id=str(role["id"]), payload=payload)
        return state

    def send(self, verb: Verb, item: PlanItem) -> None:
        """Apply one planned operation. Never called for a no-op, and never for anything else."""
        if item.kind == "createRole":
            if verb == "create":
                self._graphql(CREATE_ROLE_MUTATION, {"input": dict(item.payload)})
            else:
                self._graphql(UPDATE_ROLE_MUTATION, {"id": item.record_id, "update": dict(item.payload)})
            return
        response = (
            self._client.post(self._collection_url(item.kind), json=dict(item.payload))
            if verb == "create"
            else self._client.patch(self._collection_url(item.kind, item.record_id), json=dict(item.payload))
        )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise TransportError(response.status_code)


# --- Deploy ------------------------------------------------------------------------------------


def deploy(
    target: str,
    artifact_path: Path,
    transport: Transport | None,
    dry_run: bool = False,
) -> Receipt:
    """Validate, plan, and (unless `dry_run`) apply one artifact to one target.

    `transport` is `None` only offline: a dry run with no credentials plans against the empty-state
    assumption, which is the honest answer when the target cannot be read. An apply with no
    transport is a configuration error, raised by `resolve_target` before this point.
    """
    findings = validation_findings(artifact_path)
    if findings:
        msg = f"artifact {artifact_path} is not valid — refusing to apply:\n" + "\n".join(findings)
        raise DeployError(msg)

    artifact = json.loads(artifact_path.read_text())
    operations: tuple[Mapping[str, Any], ...] = tuple(artifact["operations"])
    state = transport.read_state() if transport is not None else {}
    items = plan(operations, state)

    # A dry run's counts are the plan's; an apply's are what actually went out, so a run stopped
    # by a failure reports the creates it made, not the ones it intended.
    applied = sum(1 for item in items if item.verb is not None) if dry_run else 0
    failure: str | None = None
    if not dry_run:
        if transport is None:  # pragma: no cover — resolve_target refuses first
            msg = f"target {target!r} has no transport — cannot apply"
            raise DeployError(msg)
        for item in items:
            if item.verb is None:
                continue
            try:
                transport.send(item.verb, item)
            except TransportError as error:
                # Fail fast: a field create behind a failed object create is guaranteed noise.
                failure = f"{item.name}: status {error.status}"
                break
            applied += 1

    return Receipt(
        target=target,
        artifact=str(artifact_path),
        checksum=artifact_checksum(artifact_path),
        dry_run=dry_run,
        counts=_counts(items, applied),
        operations=plan_lines(items),
        failure=failure,
    )


def _build_transport(target: str, env: Mapping[str, str], dry_run: bool) -> Transport | None:
    """The target's transport, or `None` for an offline dry run."""
    try:
        resolved = resolve_target(target, env)
    except DeployError:
        if dry_run:
            return None
        raise
    return MetadataApiTransport(resolved)


def main(
    argv: list[str] | None = None, env: Mapping[str, str] | None = None, transport: Transport | None = None
) -> int:
    """CLI entry point: print the plan, apply unless `--dry-run`, print the receipt.

    `env` and `transport` are injected by tests; the CLI reads `os.environ` and builds the HTTP
    transport from the resolved target.
    """
    parser = argparse.ArgumentParser(description="Apply the validated Twenty metadata artifact to one target.")
    parser.add_argument("--target", required=True, choices=TARGET_NAMES, help="which instance to apply to")
    parser.add_argument("--artifact", type=Path, default=ARTIFACT_PATH, help="artifact file to apply")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; send no mutating operation")
    args = parser.parse_args(argv)

    environment = os.environ if env is None else env
    try:
        resolved_transport = (
            transport if transport is not None else _build_transport(args.target, environment, args.dry_run)
        )
        receipt = deploy(
            target=args.target,
            artifact_path=args.artifact,
            transport=resolved_transport,
            dry_run=args.dry_run,
        )
    except DeployError as error:
        print(str(error))
        return 1

    if args.dry_run:
        print("\n".join(receipt.operations))
    print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
    return 1 if receipt.failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
