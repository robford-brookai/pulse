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
  is `role:<label>` — also stable, also named in the artifact (the live Role type has no name).
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
from pulse_core.twenty_validate import check_schema, encode_option_value, validate

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

#: The role read and writes, corrected against the live dev instance (4.1 read-back,
#: 2026-08-16). The live `Role` type has no `name` — a role's stable identity is its `label` —
#: and its permission records reference metadata by id (`objectMetadataId`/`fieldMetadataId`),
#: not by name. Permissions apply through their own upsert mutations, never through the role
#: create/update inputs, which take scalars only.
ROLES_QUERY = (
    "query DeployReadRoles { getRoles { id label description canUpdateAllSettings"
    " canReadAllObjectRecords canUpdateAllObjectRecords canSoftDeleteAllObjectRecords"
    " canDestroyAllObjectRecords"
    " objectPermissions { objectMetadataId canReadObjectRecords canUpdateObjectRecords"
    " canSoftDeleteObjectRecords canDestroyObjectRecords }"
    " fieldPermissions { objectMetadataId fieldMetadataId canReadFieldValue canUpdateFieldValue } } }"
)
CREATE_ROLE_MUTATION = (
    "mutation DeployCreateRole($input: CreateRoleInput!) { createOneRole(createRoleInput: $input) { id } }"
)
UPDATE_ROLE_MUTATION = (
    "mutation DeployUpdateRole($id: UUID!, $update: UpdateRolePayload!)"
    " { updateOneRole(updateRoleInput: {id: $id, update: $update}) { id } }"
)
UPSERT_OBJECT_PERMISSIONS_MUTATION = (
    "mutation DeployUpsertObjectPermissions($input: UpsertObjectPermissionsInput!)"
    " { upsertObjectPermissions(upsertObjectPermissionsInput: $input) { objectMetadataId } }"
)
UPSERT_FIELD_PERMISSIONS_MUTATION = (
    "mutation DeployUpsertFieldPermissions($input: UpsertFieldPermissionsInput!)"
    " { upsertFieldPermissions(upsertFieldPermissionsInput: $input) { fieldMetadataId } }"
)

#: The scalar half of a role payload — what `createOneRole`/`updateOneRole` accept. The
#: permission lists ride the same payload for planning, and the transport splits them out to
#: the upsert mutations at send time.
ROLE_SCALARS = (
    "label",
    "description",
    "canUpdateAllSettings",
    "canReadAllObjectRecords",
    "canUpdateAllObjectRecords",
    "canSoftDeleteAllObjectRecords",
    "canDestroyAllObjectRecords",
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
    """One artifact operation resolved against the target's state.

    `payload` is what drift is computed on and what an update sends; `create_extras` is the
    create-only remainder the server requires but never reads back (a relation's target end).
    """

    key: str
    kind: str
    name: str
    payload: Mapping[str, Any]
    record_id: str | None = None
    verb: Verb | None = None
    create_extras: Mapping[str, Any] | None = None


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
    # The live Role type has no `name` (4.1 read-back) — the label is the identity that
    # round-trips, and it is equally stable and equally named in the artifact.
    return f"role:{operation['label']}"


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
    """A relation operation as the fields surface round-trips it: a RELATION field, from side.

    v2.30 has no relations collection (DNA-909 receipt) — the from-side field carries the
    relation, and the key stays the from side's `universalIdentifier`, so idempotence is
    unchanged. Only the keys the fields listing reports back live here (4.1 first contact);
    the target end rides `relation_creation_extras` at create time, because the listing never
    echoes it and comparing on it would plan a phantom update forever.
    """
    from_end = operation["from"]
    payload = {
        "universalIdentifier": from_end["universalIdentifier"],
        "objectNameSingular": from_end["objectNameSingular"],
        "name": from_end["fieldName"],
        "label": from_end["label"],
        "type": "RELATION",
    }
    if "isNullable" in from_end:
        payload["isNullable"] = from_end["isNullable"]
    return payload


def relation_creation_extras(operation: Mapping[str, Any]) -> dict[str, Any]:
    """The create-only half of a relation: the target end, as `relationCreationPayload`.

    The live server requires it on create and never reads it back (4.1 first contact) — the
    inverse field it creates carries a server-minted identifier, so the artifact's to-side
    `universalIdentifier` cannot be applied (identifiers are immutable; HANDOFF.md). Names
    stay environment-independent; the transport resolves the target object's metadata id.
    """
    to_end = operation["to"]
    return {
        "relationCreationPayload": {
            "type": operation["type"],
            "targetObjectNameSingular": to_end["objectNameSingular"],
            "targetFieldLabel": to_end["label"],
            "targetFieldIcon": "IconRelationOneToMany",
        }
    }


def role_payload(operation: Mapping[str, Any]) -> dict[str, Any]:
    """A role operation in the terms the live server round-trips (4.1 read-back, 2026-08-16).

    Environment-independent on purpose — permissions name objects and fields by
    `objectNameSingular`/`fieldName`, and the transport resolves those to the target's metadata
    ids at send time — so the same artifact plans identically against every target.

    Three semantic translations, none lossless:

    - The artifact's `name` is dropped: the live Role type has none, so the label is the
      identity (see `operation_key`).
    - There is no object-level create permission on v2.30 — record creation rides the update
      permission — so `canUpdateObjectRecords` is `canCreate or canUpdate`. And the server
      refuses write-without-read (`CANNOT_GIVE_WRITING_PERMISSION_ON_NON_READABLE_OBJECT`), so
      read is implied by any write grant. A create-only grant (the producer role) therefore
      also grants update and read; flagged in HANDOFF.md.
    - Field permissions can only restrict, never grant (live rule): a permission carries
      `canReadFieldValue`/`canUpdateFieldValue` only when the artifact denies it, and an
      entry that restricts nothing is not sent at all.

    The all-records flags are always explicit and always false: this model grants per-object,
    and leaving a flag to a server-side default could silently over-grant.
    """
    object_permissions = sorted(
        (
            {
                "objectNameSingular": permission["objectNameSingular"],
                "canReadObjectRecords": permission["canRead"] or permission["canCreate"] or permission["canUpdate"],
                "canUpdateObjectRecords": permission["canCreate"] or permission["canUpdate"],
                "canSoftDeleteObjectRecords": permission["canDelete"],
                "canDestroyObjectRecords": False,
            }
            for permission in operation["objectPermissions"]
        ),
        key=lambda permission: str(permission["objectNameSingular"]),
    )
    field_permissions = []
    for permission in operation["fieldPermissions"]:
        restrictions = {
            flag: False
            for flag, allowed in (
                ("canReadFieldValue", permission["canRead"]),
                ("canUpdateFieldValue", permission["canUpdate"]),
            )
            if not allowed
        }
        if restrictions:
            field_permissions.append({
                "objectNameSingular": permission["objectNameSingular"],
                "fieldName": permission["fieldName"],
                **restrictions,
            })
    field_permissions.sort(key=lambda permission: (str(permission["objectNameSingular"]), str(permission["fieldName"])))
    return {
        "label": operation["label"],
        "description": operation["description"],
        "canUpdateAllSettings": False,
        "canReadAllObjectRecords": False,
        "canUpdateAllObjectRecords": False,
        "canSoftDeleteAllObjectRecords": False,
        "canDestroyAllObjectRecords": False,
        "objectPermissions": object_permissions,
        "fieldPermissions": field_permissions,
    }


def desired_payload(operation: Mapping[str, Any]) -> dict[str, Any]:
    """The operation as a request body: everything except the discriminator we route on.

    Three reshapes, all toward what v2.30 actually serves: a relation plans and sends as the
    RELATION field payload the fields surface takes, a role plans in the label-keyed,
    restriction-only permission terms of the metadata GraphQL (see `role_payload`), and a
    SELECT field's option values encode to the UPPER_SNAKE_CASE tokens the live server
    stores (see `encode_option_value` — the artifact keeps the catalog vocabulary).
    """
    if operation["operation"] == "createRelation":
        return relation_field_payload(operation)
    if operation["operation"] == "createRole":
        return role_payload(operation)
    payload = {key: value for key, value in operation.items() if key != "operation"}
    if payload.get("options"):
        payload["options"] = [
            {**option, "value": encode_option_value(str(option["value"]))} for option in payload["options"]
        ]
        if isinstance(payload.get("defaultValue"), str):
            # A SELECT default names an option value — same encoding, inside the SQL-ish quotes.
            payload["defaultValue"] = f"'{encode_option_value(payload['defaultValue'].strip(chr(39)))}'"
    if payload.get("isUnique"):
        # Live rule (4.1 first contact): a unique field cannot carry a default — two records on
        # the default would collide on the unique index, and the server refuses the create.
        payload.pop("defaultValue", None)
    return payload


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
                create_extras=relation_creation_extras(operation)
                if operation["operation"] == "createRelation"
                else None,
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
        # name ↔ metadata-id maps, filled by `read_state` (which `deploy` always runs first).
        self._object_ids: dict[str, str] = {}
        self._field_ids: dict[tuple[str, str], str] = {}
        self._object_names: dict[str, str] = {}
        self._field_names: dict[str, tuple[str, str]] = {}

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

        The listings double as the id maps role permissions need: the plan names objects and
        fields by name (environment-independent), the server by metadata id, and this read is
        where the two meet. Objects are read first because a live field record carries
        `objectMetadataId`, not `objectNameSingular` (4.1 read-back) — the field's payload is
        enriched with the name the plan compares on. Roles translate the same way.
        """
        state: dict[str, RemoteRecord] = {}
        listings: dict[str, list[dict[str, Any]]] = {}
        for collection in ("objects", "fields"):
            listings[collection] = self._list_all(collection)
        self._remember_id_maps(listings["objects"], listings["fields"])
        for collection in ("objects", "fields"):
            for record in listings[collection]:
                payload = {name: value for name, value in record.items() if name != "id"}
                if collection == "fields" and "objectMetadataId" in payload:
                    object_id = str(payload["objectMetadataId"])
                    payload["objectNameSingular"] = self._object_names.get(object_id, object_id)
                if isinstance(payload.get("options"), list):
                    # The listing decorates options with server-side keys (`id`, `color`) the
                    # artifact never names — reduce to the declared keys so a matching SELECT
                    # compares equal instead of planning a phantom update (4.1 first contact).
                    payload["options"] = [
                        {name: option.get(name) for name in ("universalIdentifier", "value", "label", "position")}
                        for option in sorted(payload["options"], key=lambda option: option.get("position") or 0)
                    ]
                key = str(record["universalIdentifier"])
                state[key] = RemoteRecord(record_id=str(record["id"]), payload=payload)
        for role in self._graphql(ROLES_QUERY).get("getRoles") or ():
            state[f"role:{role['label']}"] = RemoteRecord(
                record_id=str(role["id"]), payload=self._role_remote_payload(role)
            )
        return state

    def _list_all(self, collection: str) -> list[dict[str, Any]]:
        """One collection, every page. The live listings cap at 200 records and cursor-paginate
        (4.1 first contact: a workspace ships 560 standard fields before ours land) — a single
        unpaginated GET would silently truncate the state and turn no-ops into failed creates."""
        records: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, str] = {"limit": "200"}
            if cursor is not None:
                params["starting_after"] = cursor
            response = self._client.get(f"{METADATA_ROOT}/{collection}", params=params)
            if response.status_code >= httpx.codes.BAD_REQUEST:
                raise TransportError(response.status_code)
            body = response.json()
            records.extend(body.get("data", ()))
            page_info = body.get("pageInfo") or {}
            cursor = page_info.get("endCursor")
            if not page_info.get("hasNextPage") or cursor is None:
                return records

    def _remember_id_maps(self, objects: list[dict[str, Any]], fields: list[dict[str, Any]]) -> None:
        """Cache the name ↔ metadata-id maps role permissions and field enrichment translate through.

        A live field record names its object by `objectMetadataId`; a test fixture may name it
        directly by `objectNameSingular`. Both resolve to the same map key.
        """
        self._object_ids = {str(record["nameSingular"]): str(record["id"]) for record in objects}
        self._object_names = {record_id: name for name, record_id in self._object_ids.items()}
        self._field_ids = {}
        for record in fields:
            object_id = str(record.get("objectMetadataId", ""))
            object_name = str(record.get("objectNameSingular") or self._object_names.get(object_id, object_id))
            self._field_ids[(object_name, str(record["name"]))] = str(record["id"])
        self._field_names = {record_id: names for names, record_id in self._field_ids.items()}

    def _role_remote_payload(self, role: Mapping[str, Any]) -> dict[str, Any]:
        """One role as the plan compares it: ids back to names, restriction flags only when set."""
        object_permissions = sorted(
            (
                {
                    "objectNameSingular": self._object_names.get(
                        str(permission["objectMetadataId"]), str(permission["objectMetadataId"])
                    ),
                    "canReadObjectRecords": permission["canReadObjectRecords"],
                    "canUpdateObjectRecords": permission["canUpdateObjectRecords"],
                    "canSoftDeleteObjectRecords": permission["canSoftDeleteObjectRecords"],
                    "canDestroyObjectRecords": permission["canDestroyObjectRecords"],
                }
                for permission in role.get("objectPermissions") or ()
            ),
            key=lambda permission: str(permission["objectNameSingular"]),
        )
        field_permissions = []
        for permission in role.get("fieldPermissions") or ():
            object_name, field_name = self._field_names.get(
                str(permission["fieldMetadataId"]), ("", str(permission["fieldMetadataId"]))
            )
            restrictions = {
                flag: False for flag in ("canReadFieldValue", "canUpdateFieldValue") if permission.get(flag) is False
            }
            if restrictions:
                field_permissions.append({"objectNameSingular": object_name, "fieldName": field_name, **restrictions})
        field_permissions.sort(
            key=lambda permission: (str(permission["objectNameSingular"]), str(permission["fieldName"]))
        )
        return {
            name: value for name, value in role.items() if name not in ("id", "objectPermissions", "fieldPermissions")
        } | {"objectPermissions": object_permissions, "fieldPermissions": field_permissions}

    def send(self, verb: Verb, item: PlanItem) -> None:
        """Apply one planned operation. Never called for a no-op, and never for anything else."""
        if item.kind == "createRole":
            self._send_role(verb, item)
            return
        body = dict(item.payload)
        if verb == "create" and item.create_extras is not None:
            body |= item.create_extras
            if "relationCreationPayload" in body:
                creation = dict(body["relationCreationPayload"])
                creation["targetObjectMetadataId"] = self._object_ids[str(creation.pop("targetObjectNameSingular"))]
                body["relationCreationPayload"] = creation
        # The fields surface takes `objectMetadataId`, not the plan's environment-independent
        # `objectNameSingular` (4.1 first contact) — translate at this boundary only.
        if item.kind in ("createField", "createRelation") and "objectNameSingular" in body:
            body["objectMetadataId"] = self._object_ids[str(body.pop("objectNameSingular"))]
        response = (
            self._client.post(self._collection_url(item.kind), json=body)
            if verb == "create"
            else self._client.patch(self._collection_url(item.kind, item.record_id), json=body)
        )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise TransportError(response.status_code)

    def _send_role(self, verb: Verb, item: PlanItem) -> None:
        """A role lands in up to three mutations: the scalar create/update, then the upserts.

        The role inputs take scalars only (live shape, 4.1); the permission lists apply through
        `upsertObjectPermissions`/`upsertFieldPermissions` against the role's id — returned by
        the create, carried on the plan item for an update. Permission names resolve to this
        target's metadata ids through the maps `read_state` cached.
        """
        scalars = {name: item.payload[name] for name in ROLE_SCALARS}
        if verb == "create":
            created = self._graphql(CREATE_ROLE_MUTATION, {"input": scalars})
            role_id = str((created.get("createOneRole") or {}).get("id"))
        else:
            self._graphql(UPDATE_ROLE_MUTATION, {"id": item.record_id, "update": scalars})
            role_id = str(item.record_id)
        object_permissions = [
            {
                "objectMetadataId": self._object_ids[str(permission["objectNameSingular"])],
                **{name: value for name, value in permission.items() if name != "objectNameSingular"},
            }
            for permission in item.payload["objectPermissions"]
        ]
        if object_permissions:
            self._graphql(
                UPSERT_OBJECT_PERMISSIONS_MUTATION,
                {"input": {"roleId": role_id, "objectPermissions": object_permissions}},
            )
        field_permissions = [
            {
                "objectMetadataId": self._object_ids[str(permission["objectNameSingular"])],
                "fieldMetadataId": self._field_ids[
                    (str(permission["objectNameSingular"]), str(permission["fieldName"]))
                ],
                **{
                    name: value for name, value in permission.items() if name not in ("objectNameSingular", "fieldName")
                },
            }
            for permission in item.payload["fieldPermissions"]
        ]
        if field_permissions:
            self._graphql(
                UPSERT_FIELD_PERMISSIONS_MUTATION,
                {"input": {"roleId": role_id, "fieldPermissions": field_permissions}},
            )


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
