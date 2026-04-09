"""Tests for the graph diff engine."""

import json
import pytest
from pathlib import Path

from backend.app.services.diff_service import diff_form_graphs

REF_PATH = Path(__file__).parent.parent.parent / "reference-data" / "form-graph-vollmacht-ausweis.json"


@pytest.fixture
def base_graph():
    return json.loads(REF_PATH.read_text())


def test_identical_graphs(base_graph):
    result = diff_form_graphs(base_graph, base_graph)
    assert result.severity == "none"
    assert len(result.field_changes) == 0
    assert len(result.step_changes) == 0


def test_cosmetic_label_change(base_graph):
    modified = json.loads(json.dumps(base_graph))
    # Slightly rename a field label (Levenshtein < 3)
    modified["steps"][1]["sections"][0]["fields"][1]["label"] = "Vornamen"  # was "Vorname"
    result = diff_form_graphs(base_graph, modified)
    assert result.severity == "cosmetic"
    assert any(fc.change_type == "label_changed" for fc in result.field_changes)


def test_structural_field_added(base_graph):
    modified = json.loads(json.dumps(base_graph))
    modified["steps"][1]["sections"][0]["fields"].append({
        "label": "Zweiter Vorname",
        "type": "text",
        "required": False,
    })
    result = diff_form_graphs(base_graph, modified)
    assert result.severity == "structural"
    assert any(fc.change_type == "added" and fc.field_label == "Zweiter Vorname"
               for fc in result.field_changes)


def test_structural_type_changed(base_graph):
    modified = json.loads(json.dumps(base_graph))
    # Change Anrede from select to radio
    modified["steps"][1]["sections"][0]["fields"][0]["type"] = "radio"
    result = diff_form_graphs(base_graph, modified)
    assert result.severity == "structural"
    assert any(fc.change_type == "type_changed" for fc in result.field_changes)


def test_breaking_required_field_removed(base_graph):
    modified = json.loads(json.dumps(base_graph))
    # Remove the required "Vorname" field
    modified["steps"][1]["sections"][0]["fields"] = [
        f for f in modified["steps"][1]["sections"][0]["fields"]
        if f["label"] != "Vorname"
    ]
    result = diff_form_graphs(base_graph, modified)
    assert result.severity == "breaking"
    assert any(fc.change_type == "removed" and "Vorname" in fc.field_label
               for fc in result.field_changes)


def test_breaking_step_removed(base_graph):
    modified = json.loads(json.dumps(base_graph))
    # Remove step 3
    modified["steps"] = [s for s in modified["steps"] if s.get("step") != 3]
    result = diff_form_graphs(base_graph, modified)
    assert result.severity == "breaking"
    assert any(sc.change_type == "removed" for sc in result.step_changes)


def test_structural_options_changed(base_graph):
    modified = json.loads(json.dumps(base_graph))
    # Add option to Anrede select
    modified["steps"][1]["sections"][0]["fields"][0]["options"] = [
        "Herr", "Frau", "Divers", "Keine Angabe"
    ]
    result = diff_form_graphs(base_graph, modified)
    assert result.severity == "structural"
    assert any(fc.change_type == "options_changed" for fc in result.field_changes)


def test_summary_de_content(base_graph):
    modified = json.loads(json.dumps(base_graph))
    modified["steps"][1]["sections"][0]["fields"].append({
        "label": "Titel",
        "type": "text",
        "required": False,
    })
    result = diff_form_graphs(base_graph, modified)
    assert "neue" in result.summary_de.lower()


def test_empty_graphs():
    result = diff_form_graphs({}, {})
    assert result.severity == "none"


def test_none_graph():
    result = diff_form_graphs(None, None)
    assert result.severity == "none"
