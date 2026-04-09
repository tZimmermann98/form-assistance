"""Integration tests for the form executor using the local HTML fixture.

Tests run against the Hundesteuer test form — no live city server or API key needed.
"""

import json
import pytest
from pathlib import Path

pytest.importorskip("playwright")

FIXTURE_PATH = Path(__file__).parent.parent.parent / "explorer" / "tests" / "fixtures" / "multi_step_form.html"


@pytest.fixture
def hundesteuer_graph():
    """A minimal form graph matching the multi_step_form.html fixture."""
    return {
        "source_url": f"file://{FIXTURE_PATH}",
        "steps": [
            {
                "step": 1,
                "id": "consent",
                "title": "Einwilligungserklaerung",
                "description": "Datenschutz",
                "sections": [{
                    "section": "Datenschutzhinweis",
                    "group_rule": None,
                    "fields": [{
                        "label": "Ich habe die Datenschutzerklaerung gelesen und bin einverstanden",
                        "type": "checkbox",
                        "required": True,
                    }],
                }],
                "navigation": {"next": "halter", "back": None},
            },
            {
                "step": 2,
                "id": "halter",
                "title": "Angaben zur Halterin / zum Halter",
                "description": "Persoenliche Daten",
                "sections": [
                    {
                        "section": "Persoenliche Daten",
                        "group_rule": None,
                        "fields": [
                            {"label": "Anrede", "type": "select", "required": True, "options": ["Herr", "Frau", "Divers"]},
                            {"label": "Vorname", "type": "text", "required": True},
                            {"label": "Nachname", "type": "text", "required": True},
                            {"label": "Geburtsdatum", "type": "date", "required": True, "format": "DD.MM.YYYY"},
                        ],
                    },
                    {
                        "section": "Adresse",
                        "group_rule": None,
                        "fields": [
                            {"label": "Strasse und Hausnummer", "type": "text", "required": True},
                            {"label": "Postleitzahl", "type": "text", "required": True},
                            {"label": "Ort", "type": "text", "required": True},
                        ],
                    },
                    {
                        "section": "Kontakt",
                        "group_rule": "at_least_one_required",
                        "fields": [
                            {"label": "Telefonnummer", "type": "text", "required": False},
                            {"label": "E-Mail-Adresse", "type": "email", "required": False},
                        ],
                    },
                ],
                "navigation": {"next": "hund", "back": "consent"},
            },
            {
                "step": 3,
                "id": "hund",
                "title": "Angaben zum Hund",
                "description": "Hund",
                "sections": [{
                    "section": "Hund",
                    "group_rule": None,
                    "fields": [
                        {"label": "Name des Hundes", "type": "text", "required": True},
                        {"label": "Rasse", "type": "text", "required": True},
                        {"label": "Chipnummer", "type": "text", "required": False},
                    ],
                }],
                "navigation": {"next": "zusammenfassung", "back": "halter"},
            },
            {
                "step": 4,
                "id": "zusammenfassung",
                "title": "Zusammenfassung",
                "description": "Zusammenfassung",
                "sections": [],
                "navigation": {"next": None, "back": "hund"},
            },
        ],
        "outcome": {
            "type": "print_and_sign",
            "description": "PDF wird erstellt",
            "submission_mode": "offline",
        },
    }


@pytest.fixture
def test_field_values():
    """Test citizen data for the Hundesteuer form."""
    return {
        "anrede": "Herr",
        "vorname": "Max",
        "nachname": "Mustermann",
        "geburtsdatum": "1990-05-15",  # ISO format — executor converts to DD.MM.YYYY
        "strasse_und_hausnummer": "Musterstr. 42",
        "postleitzahl": "48149",
        "ort": "Muenster",
        "telefonnummer": "0251-12345",
        "name_des_hundes": "Bello",
        "rasse": "Labrador",
    }


@pytest.mark.asyncio
async def test_executor_fills_form(hundesteuer_graph, test_field_values):
    """Full execution against the local fixture: all fields filled, no submit."""
    from executor.runner import FormExecutor

    executor = FormExecutor()
    result = await executor.execute(
        form_graph=hundesteuer_graph,
        field_values=test_field_values,
        source_url=f"file://{FIXTURE_PATH}",
    )

    assert result["status"] == "success"
    assert result.get("screenshot_base64")

    # Audit log should have entries but no PII values
    audit = result["audit_log"]
    assert len(audit) > 0

    # No entry should contain actual PII values
    audit_text = json.dumps(audit)
    assert "Max" not in audit_text
    assert "Mustermann" not in audit_text
    assert "48149" not in audit_text
    assert "[REDACTED]" in audit_text


@pytest.mark.asyncio
async def test_executor_converts_date(hundesteuer_graph, test_field_values):
    """ISO dates should be converted to DD.MM.YYYY."""
    from executor.runner import _to_dd_mm_yyyy

    assert _to_dd_mm_yyyy("1990-05-15") == "15.05.1990"
    assert _to_dd_mm_yyyy("15.05.1990") == "15.05.1990"
    assert _to_dd_mm_yyyy("2026-01-01") == "01.01.2026"


@pytest.mark.asyncio
async def test_executor_field_not_found(hundesteuer_graph, test_field_values):
    """Missing field in the HTML should trigger recheck."""
    from executor.runner import FormExecutor

    # Add a field that doesn't exist in the fixture
    bad_graph = json.loads(json.dumps(hundesteuer_graph))
    bad_graph["steps"][1]["sections"][0]["fields"].append({
        "label": "Steuernummer des Hundehalters",
        "type": "text",
        "required": True,
    })

    values = dict(test_field_values)
    values["steuernummer_des_hundehalters"] = "DE123456789"

    executor = FormExecutor()
    result = await executor.execute(
        form_graph=bad_graph,
        field_values=values,
        source_url=f"file://{FIXTURE_PATH}",
    )

    assert result["status"] == "field_not_found"
    assert result["trigger_recheck"] is True
    assert "Steuernummer" in result["error"]


@pytest.mark.asyncio
async def test_executor_missing_required_field(hundesteuer_graph):
    """Missing required field values should produce errors."""
    from executor.runner import FormExecutor

    # Only provide some fields
    partial_values = {
        "anrede": "Frau",
        "vorname": "Erika",
        # Missing: nachname, geburtsdatum, address, dog fields
    }

    executor = FormExecutor()
    result = await executor.execute(
        form_graph=hundesteuer_graph,
        field_values=partial_values,
        source_url=f"file://{FIXTURE_PATH}",
    )

    # Should still execute (partial fill) but report errors
    assert result["status"] in ("partial", "success")
    if result["status"] == "partial":
        assert len(result.get("errors", [])) > 0
