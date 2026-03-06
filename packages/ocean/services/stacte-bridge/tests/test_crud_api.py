"""Tests for stacte-bridge REST API endpoints."""
from __future__ import annotations

import pathlib
import sys

import pytest

_SVC = pathlib.Path(__file__).parents[1]
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from src.crud_api import _SCHEMA_SUMMARY, get_schema


def test_get_schema_returns_tables_and_relationships():
    """GET /schema returns tables and relationships for Vanna.ai training."""
    schema = _SCHEMA_SUMMARY
    assert "tables" in schema
    assert "relationships" in schema
    table_names = [t["name"] for t in schema["tables"]]
    assert "patients" in table_names
    assert "alerts" in table_names
    assert "tasks" in table_names
    assert "interactions" in table_names
    assert "outcomes" in table_names
    assert "patient_graph_summary" in table_names


def test_get_schema_tables_have_description():
    """Each table in schema has a description field."""
    for table in _SCHEMA_SUMMARY["tables"]:
        assert "name" in table
        assert "description" in table
        assert len(table["description"]) > 0


def test_schema_relationships_reference_tables():
    """Relationships reference patient-centered graph structure."""
    rels = _SCHEMA_SUMMARY["relationships"]
    assert any("patients" in r for r in rels)
    assert any("alerts" in r for r in rels)
    assert any("tasks" in r for r in rels)


@pytest.mark.asyncio
async def test_get_schema_endpoint_returns_dict():
    """get_schema() coroutine returns the expected dict structure."""
    result = await get_schema()
    assert isinstance(result, dict)
    assert "tables" in result
    assert "relationships" in result
