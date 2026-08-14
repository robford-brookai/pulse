"""Model-definition and UID-map tests (pulse-app-scaffold 2.1).

Three properties, per the task's test contract:

1. The model definition validates — every relation names a defined object and is mirrored by its
   inverse, and every dimension-bound SELECT names a catalog subject.
2. The UID map covers exactly the model + catalog surface: nothing missing, nothing orphaned.
3. Every identifier is a well-formed UUID and no identifier is reused.

Plus the negative cases, because an invariant nothing can violate is not an invariant: each
validator is shown rejecting a minimally-broken definition.

The whole suite is pure file I/O over the committed catalog and map — no socket, no server. It
backs the `twenty-metadata-artifact` spec's "universalIdentifiers are minted once and never
regenerated" requirement on its input side: the map is data this module reads and never writes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pulse_core import twenty_model as tm
from pulse_core.catalog_gen import Catalog, load_catalog
from pydantic import ValidationError


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return load_catalog()


@pytest.fixture(scope="module")
def uid_map() -> dict[str, str]:
    return tm.load_uid_map()


# --- 1. The model definition validates -------------------------------------------------------


def test_the_committed_model_validates_against_the_committed_catalog(catalog: Catalog) -> None:
    tm.validate_against_catalog(tm.TWENTY_MODEL, catalog)


def test_the_model_carries_the_six_data_model_objects() -> None:
    assert [obj.name_singular for obj in tm.TWENTY_MODEL.objects] == [
        "patient",
        "program",
        "patientProgram",
        "provider",
        "clinic",
        "domainEvent",
    ]


def test_no_object_declares_a_base_field() -> None:
    """Scaffold-doc correction 1: Twenty adds these, and declaring one collides on sync."""
    base = {"id", "createdAt", "updatedAt", "createdBy", "deletedAt"}
    declared = {(obj.name_singular, field.name) for obj in tm.TWENTY_MODEL.objects for field in obj.fields}
    assert not {name for _, name in declared} & base


def test_every_relation_names_a_defined_object_and_is_mirrored() -> None:
    defined = {obj.name_singular for obj in tm.TWENTY_MODEL.objects}
    mirror = {"MANY_TO_ONE": "ONE_TO_MANY", "ONE_TO_MANY": "MANY_TO_ONE"}
    seen = 0
    for obj in tm.TWENTY_MODEL.objects:
        for field in obj.fields:
            if field.relation is None:
                continue
            seen += 1
            assert field.relation.target_object in defined
            target = tm.TWENTY_MODEL.object(field.relation.target_object)
            assert target is not None
            inverse = target.field(field.relation.inverse_field)
            assert inverse is not None and inverse.relation is not None
            assert inverse.relation.type == mirror[field.relation.type]
            assert inverse.relation.target_object == obj.name_singular
            assert inverse.relation.inverse_field == field.name
    assert seen == 10


def test_domain_event_keeps_three_nullable_relations_and_no_morph() -> None:
    """Scaffold-doc correction 4: explicit beats polymorphic for the reconciliation SQL."""
    domain_event = tm.TWENTY_MODEL.object("domainEvent")
    assert domain_event is not None
    relations = [field for field in domain_event.fields if field.type == "RELATION"]
    assert [field.name for field in relations] == ["patientProgram", "provider", "clinic"]
    assert all(field.is_nullable for field in relations)
    assert not any("MORPH" in field.type for field in domain_event.fields)


def test_every_declared_dimension_names_a_catalog_subject(catalog: Catalog) -> None:
    dimensions = {
        (obj.name_singular, field.name): field.dimension
        for obj in tm.TWENTY_MODEL.objects
        for field in obj.fields
        if field.dimension is not None
    }
    assert dimensions == {
        ("patientProgram", "lifecycleStatus"): "enrollment",
        ("patientProgram", "qualificationStatus"): "billing_episode",
    }
    assert set(dimensions.values()) <= set(catalog.subjects)


def test_catalog_backed_options_equal_the_subject_states(catalog: Catalog) -> None:
    patient_program = tm.TWENTY_MODEL.object("patientProgram")
    assert patient_program is not None
    lifecycle = patient_program.field("lifecycleStatus")
    assert lifecycle is not None
    values = [option.value for option in tm.resolve_options(lifecycle, catalog)]
    assert values == sorted(catalog.subjects["enrollment"].transitions)
    assert values == ["active", "ended", "on_hold", "pending_start"]


def test_the_event_type_registry_is_the_catalog_cross_product(catalog: Catalog) -> None:
    registry = tm.event_type_registry(catalog)
    expected = sorted(f"{subject}.{state}" for subject, spec in catalog.subjects.items() for state in spec.transitions)
    assert list(registry) == expected
    assert "enrollment.active" in registry
    assert len(registry) == len(set(registry))


def test_model_fixed_enums_declare_no_dimension() -> None:
    """entityType/entityRefSystem/actorType and the v1 Provider/Clinic status are not catalog state."""
    literals = {
        (obj.name_singular, field.name): tuple(option.value for option in field.options)
        for obj in tm.TWENTY_MODEL.objects
        for field in obj.fields
        if field.option_source == "literal"
    }
    assert literals == {
        ("provider", "lifecycleStatus"): ("credentialed",),
        ("clinic", "lifecycleStatus"): ("onboarded",),
        ("domainEvent", "entityType"): ("patient", "provider", "clinic"),
        ("domainEvent", "entityRefSystem"): ("brook", "sfdc", "mrn", "app"),
        ("domainEvent", "actorType"): ("human", "agent", "system"),
    }


def test_the_not_null_trio_carries_defaults() -> None:
    """Scaffold-doc correction 3 — the only three fields it names."""
    not_null = {
        (obj.name_singular, field.name): field.default_value
        for obj in tm.TWENTY_MODEL.objects
        for field in obj.fields
        if not field.is_nullable and field.type != "RELATION"
    }
    assert not_null == {
        ("patient", "canonicalPatientId"): "''",
        ("domainEvent", "eventId"): "''",
        ("domainEvent", "eventType"): "'referral.received'",
    }


def test_raw_json_is_first_class() -> None:
    """Scaffold-doc correction 2: the data-model doc's `fallback TEXT` caveat is unnecessary."""
    domain_event = tm.TWENTY_MODEL.object("domainEvent")
    assert domain_event is not None
    assert {field.name for field in domain_event.fields if field.type == "RAW_JSON"} == {"evidence", "payload"}


# --- Negative cases: each validator rejects a minimally-broken definition ---------------------


def _object(*fields: tm.FieldSpec) -> tm.ObjectSpec:
    return tm.ObjectSpec(
        name_singular="thing",
        name_plural="things",
        label_singular="Thing",
        label_plural="Things",
        icon="IconBox",
        description="fixture",
        fields=fields,
    )


def test_a_relation_to_an_undefined_object_is_rejected() -> None:
    orphan = tm.FieldSpec(
        name="ghosts",
        type="RELATION",
        label="Ghosts",
        relation=tm.RelationSpec(type="ONE_TO_MANY", target_object="ghost", inverse_field="thing"),
    )
    with pytest.raises(ValidationError, match="targets undefined object 'ghost'"):
        tm.ModelDefinition(objects=(_object(orphan),))


def test_an_unmirrored_relation_is_rejected() -> None:
    """Both sides must agree, or the sync creates two half-relations."""
    left = tm.ObjectSpec(
        name_singular="left",
        name_plural="lefts",
        label_singular="Left",
        label_plural="Lefts",
        icon="IconBox",
        description="fixture",
        fields=(
            tm.FieldSpec(
                name="rights",
                type="RELATION",
                label="Rights",
                relation=tm.RelationSpec(type="ONE_TO_MANY", target_object="right", inverse_field="left"),
            ),
        ),
    )
    right = tm.ObjectSpec(
        name_singular="right",
        name_plural="rights",
        label_singular="Right",
        label_plural="Rights",
        icon="IconBox",
        description="fixture",
        # Same direction on both sides instead of the mirror.
        fields=(
            tm.FieldSpec(
                name="left",
                type="RELATION",
                label="Left",
                relation=tm.RelationSpec(type="ONE_TO_MANY", target_object="left", inverse_field="rights"),
            ),
        ),
    )
    with pytest.raises(ValidationError, match="is not mirrored by"):
        tm.ModelDefinition(objects=(left, right))


def test_a_dimension_that_is_not_a_catalog_subject_is_rejected(catalog: Catalog) -> None:
    model = tm.ModelDefinition(
        objects=(
            _object(
                tm.FieldSpec(
                    name="status",
                    type="SELECT",
                    label="Status",
                    option_source="catalog_subject",
                    dimension="not_a_subject",
                )
            ),
        )
    )
    with pytest.raises(ValueError, match="declares dimension 'not_a_subject', not a catalog subject"):
        tm.validate_against_catalog(model, catalog)


def test_a_select_default_outside_its_options_is_rejected(catalog: Catalog) -> None:
    model = tm.ModelDefinition(
        objects=(
            _object(
                tm.FieldSpec(
                    name="status",
                    type="SELECT",
                    label="Status",
                    option_source="catalog_subject",
                    dimension="enrollment",
                    default_value="'registered'",
                )
            ),
        )
    )
    with pytest.raises(ValueError, match="defaults to 'registered', which is not one of its options"):
        tm.validate_against_catalog(model, catalog)


def test_a_not_null_field_without_a_default_is_rejected() -> None:
    with pytest.raises(ValidationError, match="is NOT NULL without a default_value"):
        tm.FieldSpec(name="code", type="TEXT", label="Code", is_nullable=False)


def test_an_unquoted_default_is_rejected() -> None:
    """Twenty defaults are literal expressions inside a string: `\"'value'\"`, not `\"value\"`."""
    with pytest.raises(ValidationError, match="must be a quoted literal"):
        tm.FieldSpec(name="code", type="TEXT", label="Code", is_nullable=False, default_value="value")


def test_a_select_without_an_option_source_is_rejected() -> None:
    with pytest.raises(ValidationError, match="declares no option_source"):
        tm.FieldSpec(name="status", type="SELECT", label="Status")


def test_a_non_select_carrying_options_is_rejected() -> None:
    with pytest.raises(ValidationError, match="carries SELECT-only option keys"):
        tm.FieldSpec(
            name="note",
            type="TEXT",
            label="Note",
            option_source="literal",
            options=(tm.OptionSpec(value="a", label="A"),),
        )


def test_a_relation_field_without_a_relation_is_rejected() -> None:
    with pytest.raises(ValidationError, match="`relation` is set exactly on RELATION fields"):
        tm.FieldSpec(name="patient", type="RELATION", label="Patient")


def test_duplicate_field_names_are_rejected() -> None:
    twice = tm.FieldSpec(name="code", type="TEXT", label="Code")
    with pytest.raises(ValidationError, match=r"duplicate fields \['code'\]"):
        _object(twice, twice)


# --- 2. The UID map covers exactly the model + catalog surface --------------------------------


def test_the_uid_map_has_no_missing_and_no_orphan_keys(uid_map: dict[str, str], catalog: Catalog) -> None:
    missing, orphan = tm.uid_map_diff(uid_map, tm.TWENTY_MODEL, catalog)
    assert missing == ()
    assert orphan == ()


def test_the_key_scheme_is_object_field_option(uid_map: dict[str, str]) -> None:
    """Design Decision 2's scheme, spot-checked at each of the three levels."""
    assert "patientProgram" in uid_map
    assert "patientProgram.lifecycleStatus" in uid_map
    assert "patientProgram.lifecycleStatus.pending_start" in uid_map
    # An event-type option value contains a dot: keys compose, they are never split back apart.
    assert "domainEvent.eventType.referral.received" in uid_map


def test_every_object_field_and_current_catalog_option_is_covered(uid_map: dict[str, str], catalog: Catalog) -> None:
    for obj in tm.TWENTY_MODEL.objects:
        assert obj.name_singular in uid_map
        for field in obj.fields:
            field_key = f"{obj.name_singular}.{field.name}"
            assert field_key in uid_map
            for option in tm.resolve_options(field, catalog):
                assert f"{field_key}.{option.value}" in uid_map


def test_a_catalog_state_with_no_map_entry_is_reported_missing(uid_map: dict[str, str], catalog: Catalog) -> None:
    """The generator's failure mode (spec: 'A missing UID is a generation error, not a mint')."""
    thinned = {key: value for key, value in uid_map.items() if key != "patientProgram.lifecycleStatus.active"}
    missing, orphan = tm.uid_map_diff(thinned, tm.TWENTY_MODEL, catalog)
    assert missing == ("patientProgram.lifecycleStatus.active",)
    assert orphan == ()


def test_a_key_the_model_never_asks_for_is_reported_orphan(uid_map: dict[str, str], catalog: Catalog) -> None:
    padded = {**uid_map, "patientProgram.retiredField": "00000000-0000-4000-8000-000000000000"}
    missing, orphan = tm.uid_map_diff(padded, tm.TWENTY_MODEL, catalog)
    assert missing == ()
    assert orphan == ("patientProgram.retiredField",)


def test_require_uid_names_the_missing_key_and_never_mints() -> None:
    with pytest.raises(KeyError, match=r"patientProgram\.ghost"):
        tm.require_uid({}, "patientProgram.ghost")


def test_the_module_cli_passes_on_the_committed_tree(capsys: pytest.CaptureFixture[str]) -> None:
    assert tm.main() == 0
    assert "keys covered against catalog" in capsys.readouterr().out


# --- 2b. Views declare an identifier surface, not a rendering ---------------------------------


def _view(**overrides: Any) -> tm.ViewSpec:
    """A minimal well-formed view over `thing.status`, for the rejection cases below."""
    defaults: dict[str, Any] = {
        "key": "thing-board",
        "name": "Things",
        "object": "thing",
        "type": "TABLE",
        "fields": ("status",),
    }
    return tm.ViewSpec(**(defaults | overrides))


_STATUS = tm.FieldSpec(
    name="status",
    type="SELECT",
    label="Status",
    option_source="literal",
    options=(tm.OptionSpec(value="open", label="Open"),),
)


def test_a_view_over_an_undefined_object_is_rejected() -> None:
    with pytest.raises(ValidationError, match="over undefined object 'ghost'"):
        tm.ModelDefinition(objects=(_object(_STATUS),), views=(_view(object="ghost"),))


def test_a_view_naming_a_field_the_object_lacks_is_rejected() -> None:
    """A view column is a UID key; a key for a field nobody declares provisions nothing."""
    with pytest.raises(ValidationError, match=r"names thing\.ghost"):
        tm.ModelDefinition(objects=(_object(_STATUS),), views=(_view(sorts=("ghost",)),))


def test_group_by_is_set_exactly_on_kanban_views() -> None:
    with pytest.raises(ValidationError, match="`group_by` is set exactly on KANBAN views"):
        _view(type="KANBAN")
    with pytest.raises(ValidationError, match="`group_by` is set exactly on KANBAN views"):
        _view(group_by="status")


def test_a_board_grouped_by_a_non_select_is_rejected() -> None:
    """Columns are a SELECT's options; grouping by a TEXT field has no column set to derive."""
    text = tm.FieldSpec(name="note", type="TEXT", label="Note")
    with pytest.raises(ValidationError, match=r"groups by thing\.note, a TEXT"):
        tm.ModelDefinition(
            objects=(_object(_STATUS, text),),
            views=(_view(type="KANBAN", group_by="note", fields=("note",)),),
        )


def test_duplicate_view_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match=r"duplicate view keys \['thing-board'\]"):
        tm.ModelDefinition(objects=(_object(_STATUS),), views=(_view(), _view(name="Other")))


def test_uid_map_keys_carry_one_key_per_syncable_view_entity(catalog: Catalog) -> None:
    model = tm.ModelDefinition(
        objects=(_object(_STATUS),),
        views=(_view(type="KANBAN", group_by="status", filters=("status",), sorts=("status",), navigation=True),),
    )
    keys = set(tm.uid_map_keys(model, catalog))
    assert {
        "view.thing-board",
        "view.thing-board.navigation",
        "view.thing-board.field.status",
        "view.thing-board.filter.status",
        "view.thing-board.sort.status",
        "view.thing-board.group.open",
    } <= keys


def test_board_columns_follow_the_catalog_rather_than_a_hand_written_list(catalog: Catalog) -> None:
    """A state ratified into `enrollment` becomes a column key with no edit to the view."""
    states = tm.subject_states(catalog, "enrollment")
    keys = set(tm.uid_map_keys(tm.TWENTY_MODEL, catalog))
    assert {f"view.patient-program-lifecycle-board.group.{state}" for state in states} <= keys


def test_the_denormalized_webhook_columns_are_declared() -> None:
    """Twenty delivers `properties.after` — the flat entity — so a relation arrives as an id.

    Without these two copies a status change cannot be resolved to a patient and a program
    without a REST read-back on the delivery path.
    """
    patient_program = tm.TWENTY_MODEL.object("patientProgram")
    assert patient_program is not None
    for name in ("canonicalPatientId", "programCode"):
        field = patient_program.field(name)
        assert field is not None
        assert field.type == "TEXT"


# --- 3. Every identifier is a well-formed, unique UUID ----------------------------------------


def test_every_identifier_is_a_canonical_uuid(uid_map: dict[str, str]) -> None:
    malformed = sorted(key for key, value in uid_map.items() if not tm.is_well_formed_uuid(value))
    assert malformed == []


def test_no_identifier_is_reused(uid_map: dict[str, str]) -> None:
    values = list(uid_map.values())
    duplicated = sorted({value for value in values if values.count(value) > 1})
    assert duplicated == []
    assert len(values) == len(uid_map)


def test_is_well_formed_uuid_rejects_the_near_misses() -> None:
    assert not tm.is_well_formed_uuid("")
    assert not tm.is_well_formed_uuid("not-a-uuid")
    # Uppercase and braced forms parse as UUIDs but are not the canonical string we store.
    assert not tm.is_well_formed_uuid("D8EBAF86-4146-4170-B674-A6C3041A2F71")
    assert not tm.is_well_formed_uuid("{d8ebaf86-4146-4170-b674-a6c3041a2f71}")
    assert tm.is_well_formed_uuid("d8ebaf86-4146-4170-b674-a6c3041a2f71")


def test_the_map_is_committed_sorted_and_json_object(uid_map: dict[str, str]) -> None:
    """Sorted on disk so a mint is a readable append-shaped diff, not a reshuffle."""
    raw = json.loads(tm.UID_MAP_PATH.read_text())
    assert list(raw) == sorted(raw)
    assert raw == uid_map
