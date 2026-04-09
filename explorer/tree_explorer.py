"""Tree-based form exploration.

Explores all reachable paths through a form, handling cross-step branching
where selecting different options on one step leads to different next steps.

Limits: max 3 branching depth, max 5 options per branch, max 10 total paths.
"""

import json
import logging
from dataclasses import dataclass, field

from explorer.recording import should_record, get_recordings_dir

from explorer.extractors.auth_detector import detect_auth_gate, bypass_auth_gate
from explorer.extractors.branch_detector import find_branch_points, branches_to_conditional_logic
from explorer.extractors.field_extractor import extract_fields, extract_page_context
from explorer.extractors.navigation import (
    fill_for_navigation,
    fill_specific_values,
    click_next_and_verify,
    get_page_signature,
    _detect_validation_errors,
)

logger = logging.getLogger(__name__)

MAX_BRANCH_DEPTH = 3
MAX_OPTIONS_PER_BRANCH = 5
MAX_TOTAL_PATHS = 10
MAX_STEPS = 15


@dataclass
class StepExploration:
    """Result of exploring a single step."""
    step_num: int
    raw_fields: list[dict]
    page_context: dict
    screenshot: bytes
    branches: list  # BranchPoint objects
    conditional_logic: dict  # {label: {option: {shows_fields, hides_fields, shows_text}}}
    auth_gate: object | None  # AuthGateResult or None
    replay_recipe: list[dict]  # What was filled to advance past this step


@dataclass
class FormPath:
    """One complete path through the form."""
    path_id: str
    branch_point: str | None
    branch_value: str | None
    step_explorations: list[StepExploration] = field(default_factory=list)


@dataclass
class ExplorationTree:
    """All discovered paths through a form."""
    common_steps: list[StepExploration] = field(default_factory=list)
    branch_paths: list[FormPath] = field(default_factory=list)
    automation_notes: dict = field(default_factory=dict)
    final_page_screenshot: bytes = b""  # Screenshot of the summary/final page (after last step)
    final_page_buttons: list[str] = field(default_factory=list)  # Button texts on the final page


async def explore_tree(
    page,
    source_url: str,
    timeout: int = 30000,
    _depth: int = 0,
) -> ExplorationTree:
    """Explore a form as a tree, discovering all reachable paths.

    Args:
        page: Playwright page already navigated to the form
        source_url: The form URL (for replaying)
        timeout: Page navigation timeout
        _depth: Current branching depth (internal, for recursion limit)
    """
    tree = ExplorationTree()
    tree.automation_notes = {"auth_gates": []}
    step_num = 0
    seen_signatures: dict[str, int] = {}  # signature -> count (for loop detection)

    while step_num < MAX_STEPS:
        step_num += 1

        # ── Loop detection: count how many times we've seen this exact page ──
        current_sig = await get_page_signature(page)
        seen_signatures[current_sig] = seen_signatures.get(current_sig, 0) + 1

        if seen_signatures[current_sig] >= 3:
            logger.warning("Loop detected at step %d — same page seen 3 times. Breaking.", step_num)
            break
        elif seen_signatures[current_sig] == 2 and step_num > 2:
            # Same page seen twice — likely a false navigation (Wicket POST reloaded same page)
            val_errors = await _detect_validation_errors(page)
            if val_errors:
                logger.info("Step %d: Validation error on retry: %s. Re-filling...", step_num, val_errors[:2])
                await fill_for_navigation(page, timeout)
                # Don't break — let it try clicking Weiter again
            else:
                logger.info("Step %d: Same page seen twice — false navigation, re-clicking Weiter", step_num)
                step_num -= 1  # Don't count this as a new step
                nav_result = await click_next_and_verify(page, timeout)
                if nav_result.get("navigated"):
                    continue  # Got to a new page, process it next iteration
                else:
                    break  # Genuinely stuck

        # ── Auth gate check ──
        auth_gate = await detect_auth_gate(page)
        if auth_gate and auth_gate.detected:
            tree.automation_notes["auth_gates"].append({
                "step": step_num,
                "type": auth_gate.auth_type,
                "action": "bypassed",
            })
            # Capture auth gate as a visible step for the user
            tree.common_steps.append(StepExploration(
                step_num=step_num,
                raw_fields=[],
                page_context={"title": auth_gate.auth_type or "Anmeldung"},
                screenshot=await page.screenshot(type="png"),
                branches=[],
                conditional_logic={},
                auth_gate=auth_gate,
                replay_recipe=[],
            ))
            bypassed = await bypass_auth_gate(page, auth_gate)
            if bypassed:
                try:
                    await page.wait_for_load_state("networkidle", timeout=timeout)
                except Exception:
                    await page.wait_for_timeout(2000)
                continue

        # ── Consent check ──
        if step_num <= 3:
            is_consent = await _is_consent_page(page)
            if is_consent:
                recipe = await fill_for_navigation(page, timeout)
                nav_result = await click_next_and_verify(page, timeout)
                navigated = nav_result["navigated"] if isinstance(nav_result, dict) else nav_result
                if not navigated:
                    # Fallback: force-click Weiter
                    from explorer.extractors.navigation import _click_next_button
                    await _click_next_button(page)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=timeout)
                    except Exception:
                        await page.wait_for_timeout(3000)
                    navigated = True

                tree.common_steps.append(StepExploration(
                    step_num=step_num,
                    raw_fields=[{"label": "Datenschutzerklaerung", "type": "checkbox", "required": True}],
                    page_context={"title": "Einwilligungserklaerung"},
                    screenshot=b"",
                    branches=[],
                    conditional_logic={},
                    auth_gate=None,
                    replay_recipe=recipe,
                ))
                if not navigated:
                    logger.warning("Failed to navigate past consent step")
                    break
                continue

        # ── Extract fields ──
        raw_fields = await extract_fields(page)
        page_context = await extract_page_context(page)
        screenshot = await page.screenshot(type="png")
        logger.info("Step %d: sub-heading='%s', %d fields",
                     step_num, page_context.get("title", ""), len(raw_fields))

        # ── Info/instruction page with no fields: just advance ──
        if len(raw_fields) == 0:
            logger.info("Step %d has 0 fields, checking for Weiter button...", step_num)

            # Wicket/MACH forms may show a blank intermediate page after POST
            # before rendering the next step. Wait and re-scan.
            await page.wait_for_timeout(2000)
            raw_fields = await extract_fields(page)
            if raw_fields:
                # Page rendered after wait — update context and fall through
                # to normal field processing below
                page_context = await extract_page_context(page)
                screenshot = await page.screenshot(type="png")
                logger.info("Step %d: after wait, found %d fields (sub-heading='%s')",
                            step_num, len(raw_fields), page_context.get("title", ""))
            else:
                from explorer.extractors.navigation import _click_next_button
                clicked = await _click_next_button(page)
                if clicked:
                    # Capture info page as a visible step for the user
                    tree.common_steps.append(StepExploration(
                        step_num=step_num,
                        raw_fields=[],
                        page_context=page_context,
                        screenshot=screenshot,
                        branches=[],
                        conditional_logic={},
                        auth_gate=None,
                        replay_recipe=[],
                    ))
                    try:
                        await page.wait_for_load_state("networkidle", timeout=timeout)
                    except Exception:
                        await page.wait_for_timeout(3000)
                    continue
                else:
                    # No Weiter button on a 0-field page = FINAL PAGE
                    logger.info("Final page reached (0 fields, no Weiter button)")
                    tree.final_page_screenshot = screenshot
                    tree.final_page_buttons = await page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll(
                            'button, a.btn, input[type="submit"], input[type="button"]'
                        ));
                        return btns.map(b => (b.textContent || b.value || '').trim()).filter(t => t.length > 0);
                    }""")
                    logger.info("Final page buttons: %s", tree.final_page_buttons)
                    # Capture final page as a visible step
                    final_context = await extract_page_context(page)
                    tree.common_steps.append(StepExploration(
                        step_num=step_num,
                        raw_fields=[],
                        page_context=final_context,
                        screenshot=screenshot,
                        branches=[],
                        conditional_logic={},
                        auth_gate=None,
                        replay_recipe=[],
                    ))
                    break

        # ── Within-step branch detection ──
        branches = []
        conditional_logic = {}
        try:
            branches = await find_branch_points(page, raw_fields)
            conditional_logic = branches_to_conditional_logic(branches)
        except Exception as e:
            logger.warning("Branch detection failed on step %d: %s", step_num, e)

        # ── Cross-step branch detection ──
        if _depth < MAX_BRANCH_DEPTH:
            cross_branches = await _detect_cross_step_branches(
                page, raw_fields, source_url, tree.common_steps, timeout
            )

            if cross_branches:
                # Record this step as the last common step
                step_exploration = StepExploration(
                    step_num=step_num,
                    raw_fields=raw_fields,
                    page_context=page_context,
                    screenshot=screenshot,
                    branches=branches,
                    conditional_logic=conditional_logic,
                    auth_gate=auth_gate,
                    replay_recipe=[],
                )

                # Explore each branch path
                for branch_info in cross_branches[:MAX_TOTAL_PATHS]:
                    try:
                        branch_path = await _explore_branch(
                            page, source_url, tree.common_steps,
                            step_exploration, branch_info, timeout, _depth
                        )
                        tree.branch_paths.append(branch_path)
                    except Exception as e:
                        logger.error("Branch exploration failed for %s=%s: %s",
                                     branch_info["label"], branch_info["value"], e)

                return tree

        # ── No cross-step branch — continue linearly ──
        recipe = await fill_for_navigation(page, timeout)

        step_exploration = StepExploration(
            step_num=step_num,
            raw_fields=raw_fields,
            page_context=page_context,
            screenshot=screenshot,
            branches=branches,
            conditional_logic=conditional_logic,
            auth_gate=auth_gate,
            replay_recipe=recipe,
        )
        tree.common_steps.append(step_exploration)

        # Log what fill_for_navigation did
        logger.info("Step %d: fill_for_navigation returned %d fills: %s",
                     step_num, len(recipe), [r.get("label", "?") for r in recipe])

        # Navigate to next step — retry up to 3 times for cascading conditional fields
        navigated = False
        for nav_attempt in range(3):
            logger.info("Step %d: Clicking Weiter (attempt %d)...", step_num, nav_attempt + 1)
            nav_result = await click_next_and_verify(page, timeout)
            navigated = nav_result.get("navigated", False)
            val_errors = nav_result.get("validation_errors", [])

            logger.info("Step %d: click_next_and_verify result: navigated=%s, errors=%s",
                         step_num, navigated, val_errors[:3] if val_errors else "none")

            if navigated:
                break

            if val_errors and "No Weiter button" not in str(val_errors):
                # Validation error — dump page state for diagnosis
                try:
                    debug_path = f"recordings/debug_step{step_num}_attempt{nav_attempt + 1}.png"
                    await page.screenshot(path=debug_path)
                    logger.info("Step %d: Debug screenshot saved: %s", step_num, debug_path)
                except Exception:
                    pass

                current_fields = await page.evaluate("""() => {
                    const fields = [];
                    document.querySelectorAll('input:not([type=hidden]), select, textarea').forEach(el => {
                        let label = '';
                        if (el.id) {
                            const lbl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                            if (lbl) label = lbl.textContent.replace(/\\*/g,'').trim();
                        }
                        fields.push({label: label || el.name, type: el.type, value: (el.value || '').substring(0, 30), required: el.required});
                    });
                    return fields;
                }""")
                logger.info("Step %d: Page title: %s", step_num, await page.title())
                logger.info("Step %d: Current fields (%d): %s", step_num, len(current_fields),
                             json.dumps(current_fields, ensure_ascii=False))

                # Re-fill (will re-scan and find newly revealed fields)
                logger.info("Step %d: Validation error (attempt %d): %s. Re-filling...",
                            step_num, nav_attempt + 1, val_errors[:2])
                recipe2 = await fill_for_navigation(page, timeout)
                logger.info("Step %d: Re-fill returned %d fills: %s",
                             step_num, len(recipe2), [r.get("label", "?") for r in recipe2])
                step_exploration.replay_recipe.extend(recipe2)
                continue
            else:
                # Page didn't change and no validation errors — genuinely stuck
                logger.info("Step %d: Navigation failed without validation errors (attempt %d)",
                            step_num, nav_attempt + 1)
                break

        if not navigated:
            logger.info("Last step reached at step %d (navigation failed after retries)", step_num)
            break

    return tree


async def _is_consent_page(page) -> bool:
    """Check if the current page is a consent/privacy page."""
    return await page.evaluate("""() => {
        const text = document.body.innerText.toLowerCase();
        const checkboxes = document.querySelectorAll('input[type="checkbox"]');
        const hasPrivacy = text.includes('datenschutz') || text.includes('einwilligung')
            || text.includes('einverstanden');
        return checkboxes.length > 0 && checkboxes.length <= 3 && hasPrivacy;
    }""")


async def _detect_cross_step_branches(
    page, raw_fields, source_url, common_steps, timeout
) -> list[dict] | None:
    """Detect if selecting different options leads to different next pages.

    Tests selects and radios with few options. For each option:
    1. Open fresh context, replay to current step
    2. Select option, fill required, click Weiter
    3. Record the next page signature
    4. Compare signatures — if different, this is a cross-step branch.

    Returns list of {label, value, name, index, next_page_sig} or None.
    """
    # Find candidate branch elements: selects and radios with 2-5 options
    candidates = []
    for f in raw_fields:
        opts = f.get("options", [])
        if not opts or not isinstance(opts, list):
            continue
        ftype = f.get("type", "")
        name = f.get("name") or f.get("groupName")
        if not name:
            continue
        if ftype in ("select", "select-one") and 2 <= len(opts) <= MAX_OPTIONS_PER_BRANCH:
            candidates.append({"label": f.get("label", ""), "name": name, "type": "select", "options": opts})
        elif ftype == "radio" and 2 <= len(opts) <= MAX_OPTIONS_PER_BRANCH:
            candidates.append({"label": f.get("label", ""), "name": name, "type": "radio", "options": opts})

    if not candidates:
        return None

    # Test the first candidate (most likely to be the branch point)
    # Testing multiple is too expensive for session-stateful forms
    candidate = candidates[0]
    option_sigs = []

    browser = page.context.browser
    if not browser:
        return None

    for i, opt_text in enumerate(candidate["options"][:MAX_OPTIONS_PER_BRANCH]):
        try:
            # Fresh context per test
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                locale="de-DE",
            )
            test_page = await ctx.new_page()
            test_page.set_default_timeout(timeout)

            # Replay to current step
            await test_page.goto(source_url, wait_until="networkidle")
            for prev_step in common_steps:
                if prev_step.replay_recipe:
                    await fill_specific_values(test_page, prev_step.replay_recipe)
                    await click_next_and_verify(test_page, timeout)

            # Select the specific option
            if candidate["type"] == "select":
                await test_page.evaluate("""(args) => {
                    const [name, idx] = args;
                    const el = document.querySelector('select[name="' + CSS.escape(name) + '"]');
                    if (el && el.options[idx + 1]) {
                        el.selectedIndex = idx + 1;
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }""", [candidate["name"], i])
            elif candidate["type"] == "radio":
                await test_page.evaluate("""(args) => {
                    const [name, idx] = args;
                    const els = document.querySelectorAll('input[name="' + CSS.escape(name) + '"]');
                    if (els[idx]) els[idx].click();
                }""", [candidate["name"], i])

            # Fill other required fields
            await fill_for_navigation(test_page, timeout)

            # Click Weiter
            navigated = await click_next_and_verify(test_page, timeout)
            if navigated:
                sig = await get_page_signature(test_page)
                option_sigs.append({
                    "label": candidate["label"],
                    "value": opt_text,
                    "name": candidate["name"],
                    "type": candidate["type"],
                    "index": i,
                    "next_page_sig": sig,
                })
            else:
                option_sigs.append({
                    "label": candidate["label"],
                    "value": opt_text,
                    "name": candidate["name"],
                    "type": candidate["type"],
                    "index": i,
                    "next_page_sig": None,
                })

            await ctx.close()
        except Exception as e:
            logger.debug("Cross-step branch test failed for %s=%s: %s", candidate["label"], opt_text, e)

    # Check if different options lead to different pages
    valid_sigs = [s for s in option_sigs if s["next_page_sig"]]
    if len(valid_sigs) < 2:
        return None

    unique_sigs = set(s["next_page_sig"] for s in valid_sigs)
    if len(unique_sigs) <= 1:
        # All options lead to the same page — no cross-step branching
        return None

    logger.info("Cross-step branch detected on '%s': %d unique next pages from %d options",
                candidate["label"], len(unique_sigs), len(valid_sigs))
    return valid_sigs


async def _explore_branch(
    page, source_url, common_steps, branch_step, branch_info, timeout, depth
) -> FormPath:
    """Explore one branch path by replaying to the branch point and continuing."""
    browser = page.context.browser

    ctx = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        locale="de-DE",
    )
    branch_page = await ctx.new_page()
    branch_page.set_default_timeout(timeout)

    try:
        # Replay to branch step
        await branch_page.goto(source_url, wait_until="networkidle")
        for prev_step in common_steps:
            if prev_step.replay_recipe:
                await fill_specific_values(branch_page, prev_step.replay_recipe)
                await click_next_and_verify(branch_page, timeout)

        # Select the branch option
        if branch_info["type"] == "select":
            await branch_page.evaluate("""(args) => {
                const [name, idx] = args;
                const el = document.querySelector('select[name="' + CSS.escape(name) + '"]');
                if (el && el.options[idx + 1]) {
                    el.selectedIndex = idx + 1;
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }
            }""", [branch_info["name"], branch_info["index"]])
        elif branch_info["type"] == "radio":
            await branch_page.evaluate("""(args) => {
                const [name, idx] = args;
                const els = document.querySelectorAll('input[name="' + CSS.escape(name) + '"]');
                if (els[idx]) els[idx].click();
            }""", [branch_info["name"], branch_info["index"]])

        # Fill other required fields and advance
        recipe = await fill_for_navigation(branch_page, timeout)
        navigated = await click_next_and_verify(branch_page, timeout)

        # Record the branch step with its specific recipe
        branch_step_copy = StepExploration(
            step_num=branch_step.step_num,
            raw_fields=branch_step.raw_fields,
            page_context=branch_step.page_context,
            screenshot=branch_step.screenshot,
            branches=branch_step.branches,
            conditional_logic=branch_step.conditional_logic,
            auth_gate=branch_step.auth_gate,
            replay_recipe=recipe,
        )

        # Continue exploring from here
        remaining_steps = []
        if navigated:
            remaining_tree = await explore_tree(
                branch_page, source_url, timeout, _depth=depth + 1
            )
            remaining_steps = remaining_tree.common_steps

        path = FormPath(
            path_id=f"branch_{branch_info['label']}_{branch_info['value']}".replace(" ", "_").lower(),
            branch_point=branch_info["label"],
            branch_value=branch_info["value"],
            step_explorations=[branch_step_copy] + remaining_steps,
        )

    finally:
        await ctx.close()

    return path
