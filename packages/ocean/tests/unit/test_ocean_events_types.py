"""Unit tests for ocean-events type literals — new M007 additions."""

from __future__ import annotations

import typing

from ocean_events.types import EntityType, EventType, SourceSystem


def test_mongodb_connector_is_valid_source_system():
    assert "mongodb-connector" in typing.get_args(SourceSystem)


def test_patient_feature_is_valid_entity_type():
    assert "patient_feature" in typing.get_args(EntityType)


def test_patient_feature_changed_is_valid_event_type():
    assert "patient.feature.changed" in typing.get_args(EventType)
