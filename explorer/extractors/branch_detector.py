"""Detect branch points in forms — radio groups, checkboxes, and small selects.

Branch points are interactive elements that may change the form when toggled.
We test each option and record what changes (new fields, hidden fields, text changes).
"""

import logging
from dataclasses import dataclass, field

from explorer.extractors.field_extractor import extract_fields, normalize_label

logger = logging.getLogger(__name__)


@dataclass
class BranchOption:
    """One option in a branch point."""
    label: str
    index: int
    shows_fields: list[str] = field(default_factory=list)
    hides_fields: list[str] = field(default_factory=list)
    shows_text: str = ""


@dataclass
class BranchPoint:
    """A branch point — an element that changes the form when toggled."""
    label: str
    type: str  # "radio" | "checkbox" | "select"
    group_name: str  # name attribute for the group
    options: list[BranchOption] = field(default_factory=list)


async def _get_visible_labels(page) -> set[str]:
    """Get labels of all currently visible form fields."""
    labels = await page.evaluate("""() => {
        const labels = new Set();
        document.querySelectorAll('input, select, textarea').forEach(el => {
            if (el.type === 'hidden') return;
            if (el.offsetParent === null && el.type !== 'radio' && el.type !== 'checkbox') return;
            let label = '';
            if (el.id) {
                const lbl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                if (lbl) label = lbl.textContent.trim();
            }
            if (!label) {
                const wrap = el.closest('label');
                if (wrap) label = wrap.textContent.trim();
            }
            if (label) labels.add(label.replace(/\\*/g, '').trim());
        });
        return Array.from(labels);
    }""")
    return set(normalize_label(l) for l in labels)


async def _get_text_snapshot(page) -> str:
    """Get compact text snapshot for diffing."""
    try:
        text = await page.inner_text("body")
        return " ".join(text.split())[:5000]
    except Exception:
        return ""


async def find_branch_points(page, raw_fields: list[dict]) -> list[BranchPoint]:
    """Find all branch points on the current page.

    Returns branch points with their tested options and effects.
    """
    branches = []

    # Find radio groups and checkboxes with options
    for f in raw_fields:
        ftype = f.get("type", "")
        group_name = f.get("name") or f.get("groupName")
        options = f.get("options", [])

        if ftype == "radio" and group_name and options and len(options) >= 2:
            branches.append(BranchPoint(
                label=f.get("label", ""),
                type="radio",
                group_name=group_name,
                options=[BranchOption(label=opt, index=i) for i, opt in enumerate(options)],
            ))
        elif ftype == "checkbox" and group_name:
            # Skip declaration/consent checkboxes — they don't toggle field visibility
            label_lower = (f.get("label", "") or "").lower()
            _SKIP_CHECKBOX_KW = [
                "datenschutz", "einverstanden", "gelesen", "zustimm", "akzeptier",
                "erklaer", "versicher", "bestaetig", "bestätig", "pflicht",
                "hiermit", "kenntnisnahme", "richtigkeit", "bekannt", "hinterlegt",
                "wiederauffinden", "abzugeben", "pfand",
            ]
            if any(kw in label_lower for kw in _SKIP_CHECKBOX_KW):
                continue
            # Single checkboxes that might toggle content
            branches.append(BranchPoint(
                label=f.get("label", ""),
                type="checkbox",
                group_name=group_name,
                options=[
                    BranchOption(label="unchecked", index=0),
                    BranchOption(label="checked", index=1),
                ],
            ))

    # Find small selects (< 10 options) that might change form
    for f in raw_fields:
        if f.get("type") in ("select", "select-one") and f.get("options"):
            opts = f["options"]
            if isinstance(opts, list) and 2 <= len(opts) <= 10:
                group_name = f.get("name") or f.get("groupName")
                if group_name:
                    branches.append(BranchPoint(
                        label=f.get("label", ""),
                        type="select",
                        group_name=group_name,
                        options=[BranchOption(label=opt, index=i) for i, opt in enumerate(opts)],
                    ))

    if not branches:
        return []

    # Test each branch point
    baseline_labels = await _get_visible_labels(page)
    baseline_text = await _get_text_snapshot(page)

    for branch in branches:
        await _test_branch(page, branch, baseline_labels, baseline_text)

    # Filter out branches that had no effect
    return [b for b in branches if any(
        o.shows_fields or o.hides_fields or o.shows_text
        for o in b.options
    )]


async def _test_branch(
    page,
    branch: BranchPoint,
    baseline_labels: set[str],
    baseline_text: str,
):
    """Test each option in a branch point and record effects."""
    for option in branch.options:
        try:
            if branch.type == "radio":
                clicked = await page.evaluate("""(args) => {
                    const [groupName, index] = args;
                    const els = document.querySelectorAll(
                        'input[name="' + CSS.escape(groupName) + '"]'
                    );
                    if (els[index]) { els[index].click(); return true; }
                    return false;
                }""", [branch.group_name, option.index])

            elif branch.type == "checkbox":
                clicked = await page.evaluate("""(args) => {
                    const [groupName, shouldCheck] = args;
                    const el = document.querySelector(
                        'input[name="' + CSS.escape(groupName) + '"]'
                    );
                    if (!el) return false;
                    if (shouldCheck && !el.checked) el.click();
                    else if (!shouldCheck && el.checked) el.click();
                    return true;
                }""", [branch.group_name, option.index == 1])

            elif branch.type == "select":
                # Select by label text, not index — the filtered option list
                # may not match DOM indices (placeholder options are filtered out)
                clicked = await page.evaluate("""(args) => {
                    const [groupName, optionText] = args;
                    const el = document.querySelector(
                        'select[name="' + CSS.escape(groupName) + '"]'
                    );
                    if (!el) return false;
                    const target = Array.from(el.options).find(
                        o => o.textContent.trim() === optionText
                    );
                    if (!target) return false;
                    target.selected = true;
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }""", [branch.group_name, option.label])
            else:
                continue

            if not clicked:
                continue

            # Wait for dynamic updates
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            await page.wait_for_timeout(500)

            # Diff
            current_labels = await _get_visible_labels(page)
            current_text = await _get_text_snapshot(page)

            option.shows_fields = sorted(current_labels - baseline_labels)
            option.hides_fields = sorted(baseline_labels - current_labels)

            # Extract meaningful text change (not just field labels)
            if current_text != baseline_text:
                # Find new text segments
                new_words = set(current_text.split()) - set(baseline_text.split())
                if new_words:
                    # Take first 100 chars of new content
                    option.shows_text = " ".join(sorted(new_words))[:200]

        except Exception as e:
            logger.debug("Error testing branch %s option %s: %s", branch.label, option.label, e)

    # Restore: click first radio, uncheck checkbox, reset select
    try:
        if branch.type == "radio":
            await page.evaluate("""(groupName) => {
                const els = document.querySelectorAll(
                    'input[name="' + CSS.escape(groupName) + '"]'
                );
                if (els[0]) els[0].click();
            }""", branch.group_name)
        elif branch.type == "checkbox":
            await page.evaluate("""(groupName) => {
                const el = document.querySelector(
                    'input[name="' + CSS.escape(groupName) + '"]'
                );
                if (el && el.checked) el.click();
            }""", branch.group_name)
        elif branch.type == "select":
            await page.evaluate("""(groupName) => {
                const el = document.querySelector(
                    'select[name="' + CSS.escape(groupName) + '"]'
                );
                if (el) { el.selectedIndex = 0; el.dispatchEvent(new Event('change', {bubbles: true})); }
            }""", branch.group_name)

        await page.wait_for_timeout(300)
    except Exception:
        pass


def branches_to_conditional_logic(branches: list[BranchPoint]) -> dict:
    """Convert branch test results to the conditional_logic format for the form graph.

    Returns: {field_label: {option_value: {shows_fields, hides_fields, shows_text}}}
    """
    result = {}
    for branch in branches:
        effects = {}
        for option in branch.options:
            if option.shows_fields or option.hides_fields or option.shows_text:
                effects[option.label] = {
                    "shows_fields": option.shows_fields,
                    "hides_fields": option.hides_fields,
                    "shows_text": option.shows_text,
                }
        if effects:
            result[branch.label] = effects
    return result
