"""Tests for MCP tool generation from FormGraph data."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock


REF_PATH = Path(__file__).parent.parent.parent / "reference-data" / "form-graph-vollmacht-ausweis.json"


def _make_mock_form(graph_data=None, mcp_tool_spec=None, title="Test Form"):
    """Create a mock FormGraph object."""
    form = MagicMock()
    form.id = "00000000-0000-0000-0000-000000000001"
    form.title = title
    form.graph_data = graph_data
    form.mcp_tool_spec = mcp_tool_spec
    return form


def test_generate_tool_from_spec():
    """When mcp_tool_spec is present, use it directly."""
    from mcp_server.tool_generator import generate_tool_definition

    spec = {
        "tool_name": "vollmacht_ausweis",
        "description": "Vollmacht zur Abholung eines Ausweises",
        "required_inputs": [
            {"name": "vorname", "type": "string", "description": "Vorname"},
            {"name": "nachname", "type": "string", "description": "Nachname"},
        ],
        "optional_inputs": [
            {"name": "telefon", "type": "string", "description": "Telefonnummer"},
        ],
    }
    form = _make_mock_form(mcp_tool_spec=spec)
    result = generate_tool_definition(form)

    assert result is not None
    assert result["name"] == "vollmacht_ausweis"
    assert "properties" in result["input_schema"]
    assert "vorname" in result["input_schema"]["properties"]
    assert "nachname" in result["input_schema"]["properties"]
    assert "telefon" in result["input_schema"]["properties"]
    assert result["input_schema"]["required"] == ["vorname", "nachname"]


def test_auto_generate_from_graph():
    """When no mcp_tool_spec, auto-generate from graph_data."""
    from mcp_server.tool_generator import generate_tool_definition

    graph = json.loads(REF_PATH.read_text())
    form = _make_mock_form(
        graph_data=graph,
        title="Vollmacht zur Abholung eines Ausweises",
    )
    result = generate_tool_definition(form)

    assert result is not None
    assert "vollmacht" in result["name"]
    schema = result["input_schema"]
    assert schema["type"] == "object"
    # Should have multiple required fields
    assert len(schema["required"]) > 5
    # Should have properties for key fields
    props = schema["properties"]
    assert any("vorname" in k for k in props)
    assert any("nachname" in k for k in props)


def test_enum_values_for_select_fields():
    """Select fields should produce enum constraints."""
    from mcp_server.tool_generator import generate_tool_definition

    spec = {
        "tool_name": "test_form",
        "description": "Test",
        "required_inputs": [{
            "name": "anrede",
            "type": "string",
            "description": "Anrede",
            "values": ["Herr", "Frau", "Divers"],
        }],
        "optional_inputs": [],
    }
    form = _make_mock_form(mcp_tool_spec=spec)
    result = generate_tool_definition(form)

    assert result["input_schema"]["properties"]["anrede"]["enum"] == ["Herr", "Frau", "Divers"]


def test_no_data_returns_none():
    """No graph_data and no mcp_tool_spec → None."""
    from mcp_server.tool_generator import generate_tool_definition

    form = _make_mock_form(graph_data=None, mcp_tool_spec=None)
    result = generate_tool_definition(form)
    assert result is None
