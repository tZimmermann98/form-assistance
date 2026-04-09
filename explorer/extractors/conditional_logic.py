"""Detect conditional logic in forms by toggling radio/checkbox options.

For each radio/checkbox group, we:
1. Save the current page state (visible fields + text)
2. Click each option
3. Check if new fields appeared or text changed
4. Restore the original state
5. Return a mapping of option → effect
"""

import logging

from explorer.extractors.field_extractor import EXTRACT_FIELDS_JS

logger = logging.getLogger(__name__)


async def _get_visible_field_labels(page) -> set[str]:
    """Get all currently visible field labels."""
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
    return set(labels)


async def _get_page_text_snapshot(page) -> str:
    """Get a compact text snapshot of the page body."""
    try:
        text = await page.inner_text("body")
        # Collapse whitespace for comparison
        return " ".join(text.split())[:5000]
    except Exception:
        return ""


async def detect_conditional_logic(page, fields: list[dict]) -> dict[str, dict]:
    """Detect conditional logic for radio/checkbox groups on the current page.

    Args:
        page: Playwright page object
        fields: Raw extracted fields from field_extractor

    Returns:
        dict mapping field label → {option_value: "description of what changes"}
    """
    conditional = {}

    # Find radio and checkbox groups
    groups = [f for f in fields if f.get("type") in ("radio", "checkbox") and f.get("options")]

    if not groups:
        return conditional

    # Snapshot baseline state
    baseline_labels = await _get_visible_field_labels(page)
    baseline_text = await _get_page_text_snapshot(page)

    for group in groups:
        group_label = group.get("label", "")
        group_name = group.get("name") or group.get("groupName")
        options = group.get("options", [])

        if not group_name or not options or len(options) < 2:
            continue

        group_effects = {}

        for i, option_text in enumerate(options):
            try:
                # Find and click this option
                # Use label text matching since we can't use IDs
                clicked = await page.evaluate("""(args) => {
                    const [groupName, index] = args;
                    const els = document.querySelectorAll(
                        'input[name="' + CSS.escape(groupName) + '"]'
                    );
                    if (els[index]) {
                        els[index].click();
                        return true;
                    }
                    return false;
                }""", [group_name, i])

                if not clicked:
                    continue

                # Wait for any dynamic updates
                try:
                    await page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                await page.wait_for_timeout(500)

                # Check what changed
                current_labels = await _get_visible_field_labels(page)
                current_text = await _get_page_text_snapshot(page)

                new_fields = current_labels - baseline_labels
                removed_fields = baseline_labels - current_labels
                text_changed = current_text != baseline_text

                if new_fields or removed_fields or text_changed:
                    effects = []
                    if new_fields:
                        effects.append(f"Neue Felder: {', '.join(sorted(new_fields))}")
                    if removed_fields:
                        effects.append(f"Felder ausgeblendet: {', '.join(sorted(removed_fields))}")
                    if text_changed and not new_fields and not removed_fields:
                        effects.append("Seiteninhalt aendert sich")

                    group_effects[option_text] = "; ".join(effects)

            except Exception as e:
                logger.debug("Error checking conditional for %s option %s: %s", group_label, option_text, e)

        if group_effects:
            conditional[group_label] = group_effects

    # Try to restore to a neutral state — uncheck or click the first option
    for group in groups:
        group_name = group.get("name") or group.get("groupName")
        if group_name:
            try:
                await page.evaluate("""(groupName) => {
                    const els = document.querySelectorAll(
                        'input[name="' + CSS.escape(groupName) + '"]'
                    );
                    if (els[0]) els[0].click();
                }""", group_name)
            except Exception:
                pass

    return conditional
