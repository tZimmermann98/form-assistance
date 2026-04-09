"""Tests for tree-based form exploration with branching and navigation."""

import pytest
from pathlib import Path

pytest.importorskip("playwright")

BRANCHING_FIXTURE = Path(__file__).parent / "fixtures" / "branching_form.html"
BUNDID_FIXTURE = Path(__file__).parent / "fixtures" / "bundid_gate.html"
SIMPLE_FIXTURE = Path(__file__).parent / "fixtures" / "multi_step_form.html"


@pytest.fixture
async def browser_page():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        yield page
        await browser.close()


@pytest.mark.asyncio
async def test_fill_for_navigation_checks_consent(browser_page):
    """fill_for_navigation should auto-check consent checkboxes."""
    from explorer.extractors.navigation import fill_for_navigation

    await browser_page.goto(f"file://{BRANCHING_FIXTURE}")
    recipe = await fill_for_navigation(browser_page)

    # Should have checked the consent checkbox
    consent_fills = [r for r in recipe if r.get("type") == "checkbox"]
    assert len(consent_fills) >= 1

    # Checkbox should now be checked
    checked = await browser_page.evaluate("""() => {
        return document.getElementById('consent_cb').checked;
    }""")
    assert checked is True


@pytest.mark.asyncio
async def test_fill_for_navigation_fills_required(browser_page):
    """fill_for_navigation should fill required text fields and selects."""
    from explorer.extractors.navigation import fill_for_navigation

    await browser_page.goto(f"file://{BRANCHING_FIXTURE}")
    # Navigate to step 2 which has required fields
    await browser_page.evaluate("showStep('step2')")
    await browser_page.wait_for_timeout(200)

    recipe = await fill_for_navigation(browser_page)

    # Should have filled the required select and text input
    select_fills = [r for r in recipe if r.get("type") == "select"]
    text_fills = [r for r in recipe if r.get("type") in ("text", "email")]
    assert len(select_fills) >= 1
    assert len(text_fills) >= 1


@pytest.mark.asyncio
async def test_click_next_and_verify_works(browser_page):
    """click_next_and_verify should navigate and detect page change."""
    from explorer.extractors.navigation import fill_for_navigation, click_next_and_verify

    await browser_page.goto(f"file://{BRANCHING_FIXTURE}")
    # Fill consent and click next
    await fill_for_navigation(browser_page)
    navigated = await click_next_and_verify(browser_page)

    assert navigated is True
    # Should now be on step 2
    text = await browser_page.inner_text("body")
    assert "Anliegen" in text or "Halter" in text


@pytest.mark.asyncio
async def test_fill_for_navigation_enables_weiter(browser_page):
    """After filling required fields, navigation should succeed."""
    from explorer.extractors.navigation import fill_for_navigation, click_next_and_verify

    await browser_page.goto(f"file://{BRANCHING_FIXTURE}")
    # Fill required fields first
    await fill_for_navigation(browser_page)
    navigated = await click_next_and_verify(browser_page)
    assert navigated is True

    # Should now be on step 2
    step2_visible = await browser_page.evaluate(
        "() => document.getElementById('step2').classList.contains('active')"
    )
    assert step2_visible is True


@pytest.mark.asyncio
async def test_page_signature_captures_content(browser_page):
    """Page signatures should capture meaningful content."""
    from explorer.extractors.navigation import get_page_signature

    await browser_page.goto(f"file://{BRANCHING_FIXTURE}")
    sig = await get_page_signature(browser_page)

    # Should contain the heading and field labels
    assert "Hundesteuer" in sig
    assert len(sig) > 20


@pytest.mark.asyncio
async def test_tree_explore_linear_form(browser_page):
    """A form without cross-step branches should produce a linear tree."""
    from explorer.tree_explorer import explore_tree

    await browser_page.goto(f"file://{SIMPLE_FIXTURE}")
    tree = await explore_tree(browser_page, f"file://{SIMPLE_FIXTURE}")

    assert len(tree.common_steps) >= 2  # At least consent + one content step
    assert len(tree.branch_paths) == 0


@pytest.mark.asyncio
async def test_executor_resolve_steps_linear():
    """Executor should return flat steps for linear forms."""
    from executor.runner import FormExecutor

    executor = FormExecutor()
    graph = {
        "exploration_type": "linear",
        "steps": [{"step": 1, "id": "s1"}, {"step": 2, "id": "s2"}],
    }
    steps = executor._resolve_steps(graph, {})
    assert len(steps) == 2


@pytest.mark.asyncio
async def test_executor_resolve_steps_branching():
    """Executor should pick the correct branch based on field values."""
    from executor.runner import FormExecutor

    executor = FormExecutor()
    graph = {
        "exploration_type": "branching",
        "common_steps": [{"step": 1, "id": "consent"}],
        "branch_paths": [
            {
                "path_id": "branch_anmelden",
                "branch_point": "Was moechten Sie tun?",
                "branch_value": "Hund anmelden",
                "steps": [{"step": 2, "id": "anmelden_step"}],
            },
            {
                "path_id": "branch_abmelden",
                "branch_point": "Was moechten Sie tun?",
                "branch_value": "Hund abmelden",
                "steps": [{"step": 2, "id": "abmelden_step"}],
            },
        ],
    }

    # Test: select "Hund abmelden"
    steps = executor._resolve_steps(graph, {"was_moechten_sie_tun": "Hund abmelden"})
    assert len(steps) == 2
    assert steps[1]["id"] == "abmelden_step"

    # Test: select "Hund anmelden"
    steps = executor._resolve_steps(graph, {"was_moechten_sie_tun": "Hund anmelden"})
    assert len(steps) == 2
    assert steps[1]["id"] == "anmelden_step"

    # Test: no match — fallback to first branch
    steps = executor._resolve_steps(graph, {"was_moechten_sie_tun": "unknown"})
    assert len(steps) == 2
    assert steps[1]["id"] == "anmelden_step"
