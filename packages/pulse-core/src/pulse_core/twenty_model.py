"""Twenty workspace model definition — the checked-in generation input (pulse-app-scaffold 2.1).

`design/platform/twenty-data-model.md` is the model of record; `design/platform/pulse-app-scaffold.md`
corrects its assumptions and those corrections are applied here, not restated there:

1. Base fields (`id`, `createdAt`, `updatedAt`, `createdBy`, `deletedAt`) are added by Twenty and
   are therefore absent from every `ObjectSpec` — including DomainEvent's `createdAt`, which the
   data-model doc lists as `recorded_at`.
2. `RAW_JSON` is a first-class field type: `evidence` and `payload` carry it with no TEXT fallback.
3. Real NOT NULL is `is_nullable=False` plus a `default_value`, applied to the three fields the
   scaffold doc names — `patient.canonicalPatientId`, `domainEvent.eventId`, `domainEvent.eventType`.
4. Relations are declared bidirectionally (`MANY_TO_ONE` / `ONE_TO_MANY`) and DomainEvent keeps the
   three nullable relations rather than a MORPH relation.

SELECT options come from one of three sources, declared per field so the catalog binding is data
rather than generator special-casing:

- `catalog_subject` — options are the states of a named catalog subject (a *dimension*), read
  through `catalog_gen.load_catalog`. The retired registry-v1.1 seed values in the data-model doc
  (`registered`/`enrolled`/`activated`, `pending`/`qualified`/`disqualified`) are superseded by the
  ratified catalog per `design/platform/state-catalog.md`'s supersession note.
- `event_type_registry` — options are the full `<subject>.<state>` cross-product of the catalog, the
  generated form of the event-type registry the envelope spec derives from the catalog.
- `literal` — model-fixed vocabulary that the catalog does not carry (`entityType`,
  `entityRefSystem`, `actorType`, and Provider/Clinic `lifecycleStatus` at v1).

This module holds the definition and its invariants only. Rendering the options, the projection
lookup, and the Metadata API operation set is `twenty_metadata`'s job (task 2.2); this module never
opens a socket and never mints a `universalIdentifier` — `uid_map_keys` states the surface the
checked-in map must cover, and a missing key is the generator's error to raise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pulse_core.catalog_gen import Catalog, load_catalog

FieldType = Literal["TEXT", "FULL_NAME", "NUMBER", "DATE_TIME", "RAW_JSON", "SELECT", "RELATION"]
RelationType = Literal["MANY_TO_ONE", "ONE_TO_MANY"]
OptionSource = Literal["literal", "catalog_subject", "event_type_registry"]
#: Twenty's manifest-facing view types. The server also defines `*_WIDGET` variants, which it
#: provisions itself and a manifest never declares.
ViewType = Literal["TABLE", "LIST", "KANBAN", "CALENDAR"]

PACKAGE_ROOT = Path(__file__).parent
# Same reasoning as `catalog_gen.REPO_ROOT`: the app package is a repo-level artifact, not a
# package resource. Only the committed generated surfaces ship anywhere.
REPO_ROOT = PACKAGE_ROOT.parents[3]
TWENTY_APP_PATH = REPO_ROOT / "packages" / "twenty-app"
UID_MAP_PATH = TWENTY_APP_PATH / "uid-map.json"

_RELATION_MIRROR: dict[RelationType, RelationType] = {
    "MANY_TO_ONE": "ONE_TO_MANY",
    "ONE_TO_MANY": "MANY_TO_ONE",
}


def _label(value: str) -> str:
    """`billing_episode.closed` -> `Billing Episode Closed`; the human rendering of a state name."""
    return " ".join(word.capitalize() for word in value.replace(".", " ").replace("_", " ").split())


class OptionSpec(BaseModel):
    """One SELECT option. `position` and `color` are the renderer's business, not the model's."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str
    label: str


class RelationSpec(BaseModel):
    """One side of a bidirectional relation: its direction, its target, and the field facing back."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: RelationType
    target_object: str
    inverse_field: str


class FieldSpec(BaseModel):
    """One field on one object. Base fields are never declared (scaffold-doc correction 1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type: FieldType
    label: str
    description: str | None = None
    is_nullable: bool = True
    is_unique: bool = False
    # A Twenty default is a literal expression inside a string, so a string default is doubly
    # quoted: `"'pending_start'"`. Enforced below rather than left to the reader.
    default_value: str | None = None
    option_source: OptionSource | None = None
    # The catalog subject a `catalog_subject` field's options come from — the field's dimension.
    dimension: str | None = None
    options: tuple[OptionSpec, ...] = ()
    relation: RelationSpec | None = None

    @model_validator(mode="after")
    def _shape_matches_type(self) -> FieldSpec:
        if self.type == "SELECT":
            if self.option_source is None:
                msg = f"SELECT field {self.name!r} declares no option_source"
                raise ValueError(msg)
        elif self.option_source is not None or self.options or self.dimension is not None:
            msg = f"non-SELECT field {self.name!r} carries SELECT-only option keys"
            raise ValueError(msg)

        if (self.type == "RELATION") != (self.relation is not None):
            msg = f"field {self.name!r}: `relation` is set exactly on RELATION fields"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _option_source_carries_its_own_input(self) -> FieldSpec:
        if self.option_source == "literal":
            if not self.options or self.dimension is not None:
                msg = f"literal SELECT {self.name!r} needs `options` and no `dimension`"
                raise ValueError(msg)
        elif self.option_source == "catalog_subject":
            if self.dimension is None or self.options:
                msg = f"catalog_subject SELECT {self.name!r} needs `dimension` and no literal options"
                raise ValueError(msg)
        elif self.option_source == "event_type_registry" and (self.dimension is not None or self.options):
            msg = f"event_type_registry SELECT {self.name!r} takes neither `dimension` nor literal options"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _not_null_carries_a_default(self) -> FieldSpec:
        # Scaffold-doc correction 3. Relations are exempt: a required relation is enforced by the
        # foreign key, and Twenty has no literal default for one.
        if not self.is_nullable and self.type != "RELATION" and self.default_value is None:
            msg = f"field {self.name!r} is NOT NULL without a default_value"
            raise ValueError(msg)
        if self.default_value is not None and self.type in {"TEXT", "SELECT"}:
            literal = self.default_value
            if not (len(literal) >= 2 and literal.startswith("'") and literal.endswith("'")):
                msg = f"field {self.name!r} default {literal!r} must be a quoted literal, e.g. \"'value'\""
                raise ValueError(msg)
        return self

    @property
    def default_literal(self) -> str | None:
        """The default with Twenty's inner quoting stripped, for comparison against option values."""
        if self.default_value is None or self.type not in {"TEXT", "SELECT"}:
            return None
        return self.default_value[1:-1]


class ObjectSpec(BaseModel):
    """One Twenty custom object. Core objects are never modified (data-model doc, preamble)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name_singular: str
    name_plural: str
    label_singular: str
    label_plural: str
    icon: str
    description: str
    fields: tuple[FieldSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _field_names_are_unique(self) -> ObjectSpec:
        names = [field.name for field in self.fields]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            msg = f"object {self.name_singular!r} declares duplicate fields {duplicates}"
            raise ValueError(msg)
        return self

    def field(self, name: str) -> FieldSpec | None:
        return next((field for field in self.fields if field.name == name), None)


class ViewSpec(BaseModel):
    """One saved view, declared here for the identifiers it needs — not for its rendering.

    Twenty's `ViewManifestType` makes a view a syncable entity, and so is every field, filter,
    sort, and group inside it: each carries its own `universalIdentifier`. The map therefore has
    to cover them, and `uid_map_keys` is the only statement of what the map must cover — so the
    views are declared here even though the artifact carries no view operation yet.

    What lives here is the identifier surface: which view, over which object, referencing which
    fields. Presentation — position, icon, column width, visibility — stays in the hand-written
    `src/views/*.view.ts` files, because none of it needs an identifier. The two sides are held
    together by the map itself: a key the TypeScript asks for and the model does not declare fails
    `uid()` at import, and a key the model declares and nothing mints fails `check_uid_map`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The slug that names this view in the UID map — `view.<key>`. Stable across renames of the
    #: display name, which is why the key is not derived from `name`.
    key: str
    name: str
    object: str
    type: ViewType
    #: Field names in column order. Filters and sorts name fields on the same object.
    fields: tuple[str, ...] = Field(min_length=1)
    filters: tuple[str, ...] = ()
    sorts: tuple[str, ...] = ()
    #: KANBAN only: the SELECT field whose options become the board's columns.
    group_by: str | None = None
    #: Whether a navigation menu item points at this view. A view with no menu item exists but is
    #: unreachable from the sidebar, so this is declared rather than assumed.
    navigation: bool = False

    @model_validator(mode="after")
    def _group_by_belongs_to_a_board(self) -> ViewSpec:
        if (self.type == "KANBAN") != (self.group_by is not None):
            msg = f"view {self.key!r}: `group_by` is set exactly on KANBAN views"
            raise ValueError(msg)
        return self

    @property
    def referenced_fields(self) -> tuple[str, ...]:
        """Every field name this view names, deduplicated, in declaration order."""
        names = [*self.fields, *self.filters, *self.sorts]
        if self.group_by is not None:
            names.append(self.group_by)
        return tuple(dict.fromkeys(names))


class ModelDefinition(BaseModel):
    """The whole workspace model. Its invariants hold without reading the catalog."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    objects: tuple[ObjectSpec, ...] = Field(min_length=1)
    views: tuple[ViewSpec, ...] = ()

    @model_validator(mode="after")
    def _view_keys_are_unique(self) -> ModelDefinition:
        keys = [view.key for view in self.views]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            msg = f"model declares duplicate view keys {duplicates}"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _views_name_defined_fields(self) -> ModelDefinition:
        by_name = {obj.name_singular: obj for obj in self.objects}
        for view in self.views:
            target = by_name.get(view.object)
            if target is None:
                msg = f"view {view.key!r} is over undefined object {view.object!r}"
                raise ValueError(msg)
            for name in view.referenced_fields:
                if target.field(name) is None:
                    msg = f"view {view.key!r} names {view.object}.{name}, not a field on that object"
                    raise ValueError(msg)
            if view.group_by is not None:
                group_field = target.field(view.group_by)
                assert group_field is not None  # noqa: S101 — checked in the loop above
                if group_field.type != "SELECT":
                    msg = f"view {view.key!r} groups by {view.object}.{view.group_by}, a {group_field.type} — a board's columns are a SELECT's options"
                    raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _object_names_are_unique(self) -> ModelDefinition:
        names = [name for obj in self.objects for name in (obj.name_singular, obj.name_plural)]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            msg = f"model declares duplicate object names {duplicates}"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _relations_are_bidirectional(self) -> ModelDefinition:
        by_name = {obj.name_singular: obj for obj in self.objects}
        for obj in self.objects:
            for field in obj.fields:
                if field.relation is None:
                    continue
                self._check_relation(by_name, obj, field, field.relation)
        return self

    @staticmethod
    def _check_relation(
        by_name: dict[str, ObjectSpec], obj: ObjectSpec, field: FieldSpec, relation: RelationSpec
    ) -> None:
        where = f"{obj.name_singular}.{field.name}"
        target = by_name.get(relation.target_object)
        if target is None:
            msg = f"relation {where} targets undefined object {relation.target_object!r}"
            raise ValueError(msg)
        inverse = target.field(relation.inverse_field)
        if inverse is None or inverse.relation is None:
            msg = f"relation {where} names inverse {relation.target_object}.{relation.inverse_field}, not a relation"
            raise ValueError(msg)
        expected = RelationSpec(
            type=_RELATION_MIRROR[relation.type],
            target_object=obj.name_singular,
            inverse_field=field.name,
        )
        if inverse.relation != expected:
            msg = f"relation {where} is not mirrored by {relation.target_object}.{relation.inverse_field}"
            raise ValueError(msg)

    def object(self, name_singular: str) -> ObjectSpec | None:
        return next((obj for obj in self.objects if obj.name_singular == name_singular), None)


# --- Catalog binding -------------------------------------------------------------------------


def subject_states(catalog: Catalog, subject: str) -> tuple[str, ...]:
    """The states of one catalog subject, sorted — the option set of a dimension-bound SELECT."""
    return tuple(sorted(catalog.subjects[subject].transitions))


def event_type_registry(catalog: Catalog) -> tuple[str, ...]:
    """`<subject>.<state>` over every catalog subject, sorted.

    The generated form of the event-type registry `design/platform/event-envelope-spec.md` derives
    from the catalog: one state, one `noun.state` event type, no drift between the two.
    """
    return tuple(
        sorted(f"{subject}.{state}" for subject in catalog.subjects for state in subject_states(catalog, subject))
    )


def resolve_options(field: FieldSpec, catalog: Catalog) -> tuple[OptionSpec, ...]:
    """The option set a SELECT field carries, with catalog-backed sources resolved against `catalog`."""
    if field.type != "SELECT":
        return ()
    if field.option_source == "literal":
        return field.options
    if field.option_source == "catalog_subject":
        assert field.dimension is not None  # noqa: S101 — guaranteed by FieldSpec's validator
        return tuple(OptionSpec(value=state, label=_label(state)) for state in subject_states(catalog, field.dimension))
    return tuple(OptionSpec(value=value, label=_label(value)) for value in event_type_registry(catalog))


def validate_against_catalog(model: ModelDefinition, catalog: Catalog) -> None:
    """Every declared dimension names a catalog subject, and every SELECT default is an option.

    The model's own invariants are structural and hold in isolation; these two are the ones that
    only mean anything against a specific catalog version, so they are checked separately and are
    what a catalog edit can newly break.
    """
    for obj in model.objects:
        for field in obj.fields:
            where = f"{obj.name_singular}.{field.name}"
            if field.dimension is not None and field.dimension not in catalog.subjects:
                known = ", ".join(sorted(catalog.subjects))
                msg = f"{where} declares dimension {field.dimension!r}, not a catalog subject ({known})"
                raise ValueError(msg)
            default = field.default_literal
            if field.type == "SELECT" and default is not None:
                values = [option.value for option in resolve_options(field, catalog)]
                if default not in values:
                    msg = f"{where} defaults to {default!r}, which is not one of its options"
                    raise ValueError(msg)


# --- universalIdentifier map ----------------------------------------------------------------


def uid_map_keys(model: ModelDefinition, catalog: Catalog) -> tuple[str, ...]:
    """Every key the checked-in UID map must carry, sorted.

    Keyed `<object>` / `<object>.<field>` / `<object>.<field>.<option>` (design Decision 2). An
    event-type option value contains a dot, so `domainEvent.eventType.referral.received` has four
    segments — keys are built by composition and looked up whole, never split back apart.

    Views add a second family under a `view.` prefix, one key per syncable entity in the manifest:
    `view.<key>` and, beneath it, `.navigation`, `.field.<field>`, `.filter.<field>`,
    `.sort.<field>`, and `.group.<state>`. Board columns are the group-by field's resolved options,
    so a state added to the catalog becomes a column key here with no hand edit — the same
    derivation the board's TypeScript performs against `generated/options.ts`.
    """
    keys: list[str] = []
    for obj in model.objects:
        keys.append(obj.name_singular)
        for field in obj.fields:
            field_key = f"{obj.name_singular}.{field.name}"
            keys.append(field_key)
            keys.extend(f"{field_key}.{option.value}" for option in resolve_options(field, catalog))
    for view in model.views:
        view_key = f"view.{view.key}"
        keys.append(view_key)
        if view.navigation:
            keys.append(f"{view_key}.navigation")
        keys.extend(f"{view_key}.field.{name}" for name in view.fields)
        keys.extend(f"{view_key}.filter.{name}" for name in view.filters)
        keys.extend(f"{view_key}.sort.{name}" for name in view.sorts)
        if view.group_by is not None:
            target = model.object(view.object)
            assert target is not None  # noqa: S101 — guaranteed by `_views_name_defined_fields`
            group_field = target.field(view.group_by)
            assert group_field is not None  # noqa: S101 — same
            keys.extend(f"{view_key}.group.{option.value}" for option in resolve_options(group_field, catalog))
    return tuple(sorted(keys))


def load_uid_map(path: Path = UID_MAP_PATH) -> dict[str, str]:
    """Read the checked-in map. It is data, never regenerated: see design Decision 2."""
    loaded: dict[str, str] = json.loads(path.read_text())
    return loaded


def uid_map_diff(
    uid_map: dict[str, str], model: ModelDefinition, catalog: Catalog
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """`(missing, orphan)` — keys the model needs and the map lacks, and keys the model never asks for."""
    required = set(uid_map_keys(model, catalog))
    present = set(uid_map)
    return tuple(sorted(required - present)), tuple(sorted(present - required))


def require_uid(uid_map: dict[str, str], key: str) -> str:
    """Look one identifier up, or fail naming the key. Never mints — an auto-mint is the hazard."""
    try:
        return uid_map[key]
    except KeyError:
        msg = f"universalIdentifier missing for {key!r}: mint it into {UID_MAP_PATH.name} (never generated)"
        raise KeyError(msg) from None


def is_well_formed_uuid(value: str) -> bool:
    """A map value must be a canonical lowercase UUID string, not merely UUID-parseable."""
    try:
        return str(UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


# --- The model ------------------------------------------------------------------------------

_ENTITY_TYPES = ("patient", "provider", "clinic")
_ENTITY_REF_SYSTEMS = ("brook", "sfdc", "mrn", "app")
_ACTOR_TYPES = ("human", "agent", "system")


def _literal_options(*values: str) -> tuple[OptionSpec, ...]:
    return tuple(OptionSpec(value=value, label=_label(value)) for value in values)


def _as_of(dimension: str) -> FieldSpec:
    """The LWW guard beside a status field. One pair per dimension keeps dimensions isolated."""
    return FieldSpec(
        name=f"{dimension}AsOf",
        type="DATE_TIME",
        label=f"{_label(dimension)} As Of",
        description=f"Last-writer-wins guard for {dimension}: the `occurredAt` of the event that set it.",
    )


PATIENT = ObjectSpec(
    name_singular="patient",
    name_plural="patients",
    label_singular="Patient",
    label_plural="Patients",
    icon="IconUser",
    description="Identity and crosswalk only — patient state lives on PatientProgram (grain decision 2026-07-28).",
    fields=(
        FieldSpec(
            name="canonicalPatientId",
            type="TEXT",
            label="Canonical Patient ID",
            description="DIM_PATIENT_CONFORMED spine ID — the canonical identity (`entity_ref` system `brook`).",
            is_nullable=False,
            is_unique=True,
            default_value="''",
        ),
        FieldSpec(
            name="sfdcId", type="TEXT", label="Salesforce ID", description="External ID, system `sfdc`.", is_unique=True
        ),
        FieldSpec(name="mrn", type="TEXT", label="MRN", description="External ID, system `mrn`."),
        FieldSpec(name="appUserId", type="TEXT", label="App User ID", description="External ID, system `app`."),
        FieldSpec(
            name="patientPrograms",
            type="RELATION",
            label="Patient Programs",
            relation=RelationSpec(type="ONE_TO_MANY", target_object="patientProgram", inverse_field="patient"),
        ),
    ),
)

PROGRAM = ObjectSpec(
    name_singular="program",
    name_plural="programs",
    label_singular="Program",
    label_plural="Programs",
    icon="IconClipboardList",
    description="A care program. Programs are configuration, not schema (I6).",
    fields=(
        FieldSpec(
            name="code",
            type="TEXT",
            label="Code",
            description="Stable program ID carried in the envelope `program` field.",
            is_unique=True,
        ),
        FieldSpec(
            name="patientPrograms",
            type="RELATION",
            label="Patient Programs",
            relation=RelationSpec(type="ONE_TO_MANY", target_object="patientProgram", inverse_field="program"),
        ),
    ),
)

PATIENT_PROGRAM = ObjectSpec(
    name_singular="patientProgram",
    name_plural="patientPrograms",
    label_singular="Patient Program",
    label_plural="Patient Programs",
    icon="IconUserHeart",
    description="One row per patient x program — the patient-state grain. A projection target only (D2).",
    fields=(
        FieldSpec(
            name="patient",
            type="RELATION",
            label="Patient",
            is_nullable=False,
            relation=RelationSpec(type="MANY_TO_ONE", target_object="patient", inverse_field="patientPrograms"),
        ),
        FieldSpec(
            name="program",
            type="RELATION",
            label="Program",
            is_nullable=False,
            relation=RelationSpec(type="MANY_TO_ONE", target_object="program", inverse_field="patientPrograms"),
        ),
        # The two denormalized copies below exist for the webhook path, and only for it. Twenty's
        # webhook payload carries `properties.after`: the flat ORM entity, so a relation arrives as
        # `patientId` / `programId` — a foreign key, not a nested `patient` or `program` object
        # (`transform-event-to-webhook-event.ts`). A consumer that has to resolve a status change
        # back to *which patient, which program* therefore has two choices: a REST read-back per
        # delivery, which puts a credential and a network failure mode on the hot path, or these
        # two columns. Both values are pseudonymous identifiers — a spine ID and a program code,
        # never a name, a date of birth, or anything else that identifies a person.
        #
        # They are copies, so they are only as good as the writer that sets them; the projection
        # owns them the same way it owns the status fields.
        FieldSpec(
            name="canonicalPatientId",
            type="TEXT",
            label="Canonical Patient ID",
            description="Denormalized copy of `patient.canonicalPatientId`, so a webhook delivery resolves without a read-back.",
        ),
        FieldSpec(
            name="programCode",
            type="TEXT",
            label="Program Code",
            description="Denormalized copy of `program.code`, so a webhook delivery resolves without a read-back.",
        ),
        FieldSpec(
            name="lifecycleStatus",
            type="SELECT",
            label="Lifecycle Status",
            description="Enrollment state at the patient x program grain. Options from the `enrollment` catalog subject.",
            option_source="catalog_subject",
            dimension="enrollment",
            default_value="'pending_start'",
        ),
        _as_of("lifecycleStatus"),
        FieldSpec(
            name="qualificationStatus",
            type="SELECT",
            label="Qualification Status",
            description="Billing qualification. Options from the `billing_episode` catalog subject; set only by clinic-rules-engine events.",
            option_source="catalog_subject",
            dimension="billing_episode",
            default_value="'open'",
        ),
        _as_of("qualificationStatus"),
        FieldSpec(
            name="domainEvents",
            type="RELATION",
            label="Domain Events",
            relation=RelationSpec(type="ONE_TO_MANY", target_object="domainEvent", inverse_field="patientProgram"),
        ),
    ),
)

PROVIDER = ObjectSpec(
    name_singular="provider",
    name_plural="providers",
    label_singular="Provider",
    label_plural="Providers",
    icon="IconStethoscope",
    description="Registry anchor for a clinician. Carries no catalog-backed state at v1.",
    fields=(
        FieldSpec(name="sfdcId", type="TEXT", label="Salesforce ID", description="External ID, system `sfdc`."),
        FieldSpec(name="npi", type="TEXT", label="NPI", description="External ID, system `npi`."),
        FieldSpec(
            name="lifecycleStatus",
            type="SELECT",
            label="Lifecycle Status",
            # v1 literal, deliberately not bound to the `contract` subject: the catalog carries no
            # provider dimension, so a binding would assert a grain nobody has ratified. Contract
            # events stay lookup-miss no-ops until the catalog grows one (HANDOFF.md).
            description="v1 literal vocabulary; extend with the catalog when it carries a provider dimension.",
            option_source="literal",
            options=_literal_options("credentialed"),
        ),
        _as_of("lifecycleStatus"),
        FieldSpec(
            name="domainEvents",
            type="RELATION",
            label="Domain Events",
            relation=RelationSpec(type="ONE_TO_MANY", target_object="domainEvent", inverse_field="provider"),
        ),
    ),
)

CLINIC = ObjectSpec(
    name_singular="clinic",
    name_plural="clinics",
    label_singular="Clinic",
    label_plural="Clinics",
    icon="IconBuildingHospital",
    description="Registry anchor for a referring or participating clinic. Carries no catalog-backed state at v1.",
    fields=(
        FieldSpec(name="sfdcId", type="TEXT", label="Salesforce ID", description="External ID, system `sfdc`."),
        FieldSpec(
            name="lifecycleStatus",
            type="SELECT",
            label="Lifecycle Status",
            description="v1 literal vocabulary; extend with the catalog when it carries a clinic dimension.",
            option_source="literal",
            options=_literal_options("onboarded"),
        ),
        _as_of("lifecycleStatus"),
        FieldSpec(
            name="domainEvents",
            type="RELATION",
            label="Domain Events",
            relation=RelationSpec(type="ONE_TO_MANY", target_object="domainEvent", inverse_field="clinic"),
        ),
    ),
)

DOMAIN_EVENT = ObjectSpec(
    name_singular="domainEvent",
    name_plural="domainEvents",
    label_singular="Domain Event",
    label_plural="Domain Events",
    icon="IconHistory",
    description="The append-only event log. Never updated, never deleted (immutability policy).",
    fields=(
        FieldSpec(
            name="eventId",
            type="TEXT",
            label="Event ID",
            description="Producer idempotency key. Unique by convention; deduped in Snowflake.",
            is_nullable=False,
            is_unique=True,
            default_value="''",
        ),
        FieldSpec(
            name="eventType",
            type="SELECT",
            label="Event Type",
            description="Catalog-derived `<subject>.<state>` registry. Adding a type is a catalog PR.",
            option_source="event_type_registry",
            is_nullable=False,
            # A NOT NULL SELECT needs a default it can backfill with; every write supplies its own
            # event type, so this value is a constraint artifact and never a meaningful state.
            default_value="'referral.received'",
        ),
        FieldSpec(
            name="entityType",
            type="SELECT",
            label="Entity Type",
            description="Must agree with the noun in `eventType`.",
            option_source="literal",
            options=_literal_options(*_ENTITY_TYPES),
        ),
        FieldSpec(
            name="entityRefSystem",
            type="SELECT",
            label="Entity Ref System",
            description="The identifier system `entityRefId` is expressed in.",
            option_source="literal",
            options=_literal_options(*_ENTITY_REF_SYSTEMS),
        ),
        FieldSpec(name="entityRefId", type="TEXT", label="Entity Ref ID", description="ID within `entityRefSystem`."),
        FieldSpec(
            name="programCode",
            type="TEXT",
            label="Program Code",
            description="Envelope `program`; required for patient events.",
        ),
        FieldSpec(
            name="occurredAt", type="DATE_TIME", label="Occurred At", description="Business time, set by the producer."
        ),
        FieldSpec(
            name="producer",
            type="TEXT",
            label="Producer",
            description="Set by the write path from key identity, never producer-supplied.",
        ),
        FieldSpec(name="schemaVersion", type="NUMBER", label="Schema Version"),
        FieldSpec(
            name="ruleVersion",
            type="TEXT",
            label="Rule Version",
            description="The `catalog_version` in force when the event was written.",
        ),
        FieldSpec(name="correlationId", type="TEXT", label="Correlation ID", description="Journey ID across systems."),
        FieldSpec(name="causationId", type="TEXT", label="Causation ID", description="The causing event or command."),
        FieldSpec(
            name="actorType",
            type="SELECT",
            label="Actor Type",
            option_source="literal",
            options=_literal_options(*_ACTOR_TYPES),
        ),
        FieldSpec(name="actorId", type="TEXT", label="Actor ID"),
        FieldSpec(
            name="authority", type="TEXT", label="Authority", description="Approving human, where one is required."
        ),
        FieldSpec(
            name="evidence",
            type="RAW_JSON",
            label="Evidence",
            description="Source references; mandatory when `actorType` is `system`.",
        ),
        FieldSpec(name="payload", type="RAW_JSON", label="Payload", description="Unvalidated at MVP."),
        # Twenty has no polymorphic relations: three nullable relations, exactly one populated.
        FieldSpec(
            name="patientProgram",
            type="RELATION",
            label="Patient Program",
            description="Target for patient events; empty when the ref does not resolve (orphan view).",
            relation=RelationSpec(type="MANY_TO_ONE", target_object="patientProgram", inverse_field="domainEvents"),
        ),
        FieldSpec(
            name="provider",
            type="RELATION",
            label="Provider",
            relation=RelationSpec(type="MANY_TO_ONE", target_object="provider", inverse_field="domainEvents"),
        ),
        FieldSpec(
            name="clinic",
            type="RELATION",
            label="Clinic",
            relation=RelationSpec(type="MANY_TO_ONE", target_object="clinic", inverse_field="domainEvents"),
        ),
    ),
)

# --- Views ------------------------------------------------------------------------------------
#
# Declared for their identifiers (see `ViewSpec`). `key` is the slug the `src/views/*.view.ts`
# file is named after, and the two sides are checked against each other through the map.

PATIENT_PROGRAM_STATUS_BOARD_VIEW = ViewSpec(
    key="patient-program-status-board",
    name="Program Status Board",
    object="patientProgram",
    type="TABLE",
    fields=(
        "patient",
        "program",
        "lifecycleStatus",
        "lifecycleStatusAsOf",
        "qualificationStatus",
        "qualificationStatusAsOf",
    ),
    sorts=("lifecycleStatusAsOf",),
)

PATIENT_PROGRAM_LIFECYCLE_BOARD_VIEW = ViewSpec(
    key="patient-program-lifecycle-board",
    name="Lifecycle Board",
    object="patientProgram",
    type="KANBAN",
    # Columns are the `enrollment` subject's states, because that is what `lifecycleStatus`
    # resolves to. A ratified state is a column on the next generation, never a hand edit.
    group_by="lifecycleStatus",
    fields=("patient", "program", "lifecycleStatus", "lifecycleStatusAsOf", "qualificationStatus"),
    sorts=("lifecycleStatusAsOf",),
    navigation=True,
)

DOMAIN_EVENT_LOG_VIEW = ViewSpec(
    key="domain-event-log",
    name="Event Log",
    object="domainEvent",
    type="TABLE",
    fields=("occurredAt", "eventType", "entityType", "entityRefId", "programCode", "producer", "actorType"),
    sorts=("occurredAt",),
)

DOMAIN_EVENT_ORPHANS_VIEW = ViewSpec(
    key="domain-event-orphans",
    name="Orphan Events",
    object="domainEvent",
    type="TABLE",
    fields=("occurredAt", "eventType", "entityType", "entityRefSystem", "entityRefId", "programCode", "producer"),
    filters=("patientProgram", "provider", "clinic"),
    sorts=("occurredAt",),
)

TWENTY_MODEL = ModelDefinition(
    objects=(PATIENT, PROGRAM, PATIENT_PROGRAM, PROVIDER, CLINIC, DOMAIN_EVENT),
    views=(
        PATIENT_PROGRAM_STATUS_BOARD_VIEW,
        PATIENT_PROGRAM_LIFECYCLE_BOARD_VIEW,
        DOMAIN_EVENT_LOG_VIEW,
        DOMAIN_EVENT_ORPHANS_VIEW,
    ),
)


def main() -> int:
    """Report the model's UID-map coverage against the committed catalog and map."""
    catalog = load_catalog()
    validate_against_catalog(TWENTY_MODEL, catalog)
    missing, orphan = uid_map_diff(load_uid_map(), TWENTY_MODEL, catalog)
    for key in missing:
        print(f"missing universalIdentifier: {key}")
    for key in orphan:
        print(f"orphan universalIdentifier: {key}")
    if missing or orphan:
        return 1
    print(f"{len(uid_map_keys(TWENTY_MODEL, catalog))} keys covered against catalog {catalog.catalog_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
