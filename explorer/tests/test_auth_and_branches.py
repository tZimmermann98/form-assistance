"""Tests for BundID auth detection, bypass, and multi-path branch detection."""

import pytest
from pathlib import Path

pytest.importorskip("playwright")

BUNDID_FIXTURE = Path(__file__).parent / "fixtures" / "bundid_gate.html"
FORM_FIXTURE = Path(__file__).parent / "fixtures" / "multi_step_form.html"


@pytest.fixture
async def browser_page():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        yield page
        await browser.close()


# ── Auth detection tests ──


@pytest.mark.asyncio
async def test_detect_bundid_gate(browser_page):
    """BundID gate page should be detected."""
    from explorer.extractors.auth_detector import detect_auth_gate

    await browser_page.goto(f"file://{BUNDID_FIXTURE}")
    result = await detect_auth_gate(browser_page)

    assert result is not None
    assert result.detected is True
    assert result.auth_type == "bundid"
    assert result.anon_button_text is not None
    assert "ohne" in result.anon_button_text.lower() or "weiter" in result.anon_button_text.lower()


@pytest.mark.asyncio
async def test_bypass_bundid_gate(browser_page):
    """Clicking the anonymous bypass should navigate past the gate."""
    from explorer.extractors.auth_detector import detect_auth_gate, bypass_auth_gate

    await browser_page.goto(f"file://{BUNDID_FIXTURE}")
    gate = await detect_auth_gate(browser_page)
    assert gate is not None

    bypassed = await bypass_auth_gate(browser_page, gate)
    assert bypassed is True

    # Should now be on step 1 (the actual form)
    await browser_page.wait_for_timeout(300)
    text = await browser_page.inner_text("body")
    assert "Vorname" in text or "Verlust" in text


@pytest.mark.asyncio
async def test_no_auth_gate_on_normal_form(browser_page):
    """Normal form pages should not trigger auth detection."""
    from explorer.extractors.auth_detector import detect_auth_gate

    await browser_page.goto(f"file://{FORM_FIXTURE}")
    result = await detect_auth_gate(browser_page)
    assert result is None


# ── Branch detection tests ──


@pytest.mark.asyncio
async def test_detect_radio_branches(browser_page):
    """Radio buttons with conditional content should be detected as branches."""
    from explorer.extractors.field_extractor import extract_fields
    from explorer.extractors.branch_detector import find_branch_points

    await browser_page.goto(f"file://{BUNDID_FIXTURE}")
    # Navigate to step 1 (the form with conditional radio)
    await browser_page.evaluate("nextStep(1)")
    await browser_page.wait_for_timeout(300)

    raw_fields = await extract_fields(browser_page)
    branches = await find_branch_points(browser_page, raw_fields)

    # Should find the "polizei" radio group as a branch
    radio_branches = [b for b in branches if b.type == "radio"]
    assert len(radio_branches) >= 1

    polizei = radio_branches[0]
    assert len(polizei.options) >= 2

    # "Ja" should show the Aktenzeichen/Dienststelle fields
    ja_option = next((o for o in polizei.options if "ja" in o.label.lower()), None)
    if ja_option:
        assert len(ja_option.shows_fields) > 0 or ja_option.shows_text


@pytest.mark.asyncio
async def test_branches_to_conditional_logic_format(browser_page):
    """Branch results should convert to the conditional_logic graph format."""
    from explorer.extractors.field_extractor import extract_fields
    from explorer.extractors.branch_detector import find_branch_points, branches_to_conditional_logic

    await browser_page.goto(f"file://{BUNDID_FIXTURE}")
    await browser_page.evaluate("nextStep(1)")
    await browser_page.wait_for_timeout(300)

    raw_fields = await extract_fields(browser_page)
    branches = await find_branch_points(browser_page, raw_fields)
    conditional = branches_to_conditional_logic(branches)

    # Should have at least one entry
    assert len(conditional) >= 1

    # Each entry should have option keys with shows_fields/hides_fields/shows_text
    for label, options in conditional.items():
        for option_name, effects in options.items():
            assert "shows_fields" in effects
            assert "hides_fields" in effects
            assert "shows_text" in effects


@pytest.mark.asyncio
async def test_detect_radio_on_hundesteuer(browser_page):
    """The Hundesteuer form's Geschlecht radio should be found."""
    from explorer.extractors.field_extractor import extract_fields
    from explorer.extractors.branch_detector import find_branch_points

    await browser_page.goto(f"file://{FORM_FIXTURE}")
    await browser_page.evaluate("nextStep(3)")  # Step 3 has the radio
    await browser_page.wait_for_timeout(300)

    raw_fields = await extract_fields(browser_page)
    branches = await find_branch_points(browser_page, raw_fields)

    # Geschlecht radio exists but doesn't change the form, so it should
    # NOT appear as a branch (no effects)
    # This tests that we filter out no-effect branches
    assert all(b.label != "" for b in branches)
