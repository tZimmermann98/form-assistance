"""Tests for the field extractor using a local HTML fixture.

These tests use Playwright to load a local multi-step form and
verify field extraction works correctly — no LLM or network required.
"""

import pytest
from pathlib import Path

# Only run if playwright is available
pytest.importorskip("playwright")


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "multi_step_form.html"


@pytest.fixture
async def browser_page():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        yield page
        await browser.close()


@pytest.mark.asyncio
async def test_extract_fields_step1_consent(browser_page):
    """Step 1 has a single consent checkbox."""
    from explorer.extractors.field_extractor import extract_fields

    await browser_page.goto(f"file://{FIXTURE_PATH}")

    fields = await extract_fields(browser_page)

    # Should find at least the consent checkbox
    checkbox_fields = [f for f in fields if f["type"] == "checkbox"]
    assert len(checkbox_fields) >= 1

    consent = checkbox_fields[0]
    assert "Datenschutzerklaerung" in consent["label"] or "einverstanden" in consent["label"]


@pytest.mark.asyncio
async def test_extract_fields_step2_halter(browser_page):
    """Step 2 has personal data fields."""
    from explorer.extractors.field_extractor import extract_fields

    await browser_page.goto(f"file://{FIXTURE_PATH}")
    # Navigate to step 2
    await browser_page.evaluate("nextStep(2)")
    await browser_page.wait_for_timeout(200)

    fields = await extract_fields(browser_page)

    labels = [f["label"] for f in fields]
    # Should find key fields
    assert any("Vorname" in l for l in labels)
    assert any("Nachname" in l for l in labels)
    assert any("Anrede" in l for l in labels)

    # Anrede should be a select with options
    anrede = next(f for f in fields if "Anrede" in f["label"])
    assert anrede["options"] is not None
    assert len(anrede["options"]) >= 3


@pytest.mark.asyncio
async def test_extract_fields_step3_hund(browser_page):
    """Step 3 has dog info fields including radio buttons."""
    from explorer.extractors.field_extractor import extract_fields

    await browser_page.goto(f"file://{FIXTURE_PATH}")
    await browser_page.evaluate("nextStep(3)")
    await browser_page.wait_for_timeout(200)

    fields = await extract_fields(browser_page)

    labels = [f["label"] for f in fields]
    assert any("Hund" in l for l in labels)
    assert any("Rasse" in l for l in labels)

    # Should find textarea
    textarea_fields = [f for f in fields if f["type"] == "textarea"]
    assert len(textarea_fields) >= 1


@pytest.mark.asyncio
async def test_label_normalization():
    """Labels with asterisks and whitespace should be cleaned."""
    from explorer.extractors.field_extractor import normalize_label

    assert normalize_label("Vorname *") == "Vorname"
    assert normalize_label("  Nachname  *  ") == "Nachname"
    assert normalize_label("E-Mail-Adresse") == "E-Mail-Adresse"
    assert normalize_label("Geburtsdatum  Pflichtfeld") == "Geburtsdatum"


@pytest.mark.asyncio
async def test_extract_page_context(browser_page):
    """Page context should include title and headings."""
    from explorer.extractors.field_extractor import extract_page_context

    await browser_page.goto(f"file://{FIXTURE_PATH}")

    context = await extract_page_context(browser_page)

    assert "Hundesteuer" in context.get("title", "")
    assert len(context.get("headings", [])) > 0
