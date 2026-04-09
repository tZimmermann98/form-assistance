"""JavaScript-based form field extraction for Playwright pages.

Extracts all visible input/select/textarea elements with label resolution.
NEVER captures element IDs — they are session-scoped on Apache Wicket.
"""

import re

# The JavaScript function that runs in the browser context.
# Returns a list of raw field objects.
EXTRACT_FIELDS_JS = """() => {
    const fields = [];
    const seen = new Set();

    document.querySelectorAll('input, select, textarea').forEach(el => {
        if (el.type === 'hidden') return;
        if (el.offsetParent === null && el.type !== 'radio' && el.type !== 'checkbox') return;

        // Resolve label — multiple strategies
        let label = '';

        // Strategy 1: label[for=id]
        if (el.id) {
            const labelEl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
            if (labelEl) label = labelEl.textContent.trim();
        }

        // Strategy 2: closest ancestor <label>
        if (!label) {
            const closestLabel = el.closest('label');
            if (closestLabel) label = closestLabel.textContent.trim();
        }

        // Strategy 3: preceding sibling label
        if (!label) {
            let prev = el.previousElementSibling;
            while (prev) {
                if (prev.tagName === 'LABEL') {
                    label = prev.textContent.trim();
                    break;
                }
                prev = prev.previousElementSibling;
            }
        }

        // Strategy 4: parent container with a label child
        if (!label && el.parentElement) {
            const parentLabel = el.parentElement.querySelector(':scope > label');
            if (parentLabel) label = parentLabel.textContent.trim();
        }

        // Strategy 5: aria-label or title attribute
        if (!label) {
            label = el.getAttribute('aria-label') || el.getAttribute('title') || '';
        }

        // Get options for select elements
        let options = null;
        if (el.tagName === 'SELECT') {
            options = Array.from(el.options)
                .filter(o => o.value !== '' && o.value !== '-1')
                .map(o => o.textContent.trim());
        }

        // Radio/checkbox: detect group by name attribute
        let groupName = null;
        if ((el.type === 'radio' || el.type === 'checkbox') && el.name) {
            groupName = el.name;
        }

        // Detect required: HTML required, aria-required, or CSS class
        const required = el.required
            || el.getAttribute('aria-required') === 'true'
            || el.classList.contains('required');

        // Detect help text — look for sibling/adjacent help elements
        let help = '';
        const helpEl = el.parentElement?.querySelector('.help-text, .hint, .form-text, [class*="help"]');
        if (helpEl) help = helpEl.textContent.trim();

        // Build field descriptor — no element ID!
        const descriptor = {
            label: label,
            type: el.type || el.tagName.toLowerCase(),
            tagName: el.tagName.toLowerCase(),
            required: required,
            name: el.name || null,
            options: options,
            groupName: groupName,
            help: help || null,
            placeholder: el.placeholder || null,
        };

        // Deduplicate radio buttons in the same group — collect as one field
        if (groupName && (el.type === 'radio' || el.type === 'checkbox')) {
            const groupKey = groupName + ':' + el.type;
            if (seen.has(groupKey)) return;
            seen.add(groupKey);

            // Collect all options in this radio/checkbox group
            const groupEls = document.querySelectorAll(
                'input[name="' + CSS.escape(el.name) + '"]'
            );
            const groupOptions = [];
            let groupLabel = label;
            groupEls.forEach(ge => {
                // Try to get option label from adjacent text or wrapping label
                let optLabel = '';
                const wrap = ge.closest('label');
                if (wrap) {
                    optLabel = wrap.textContent.trim();
                } else if (ge.id) {
                    const lbl = document.querySelector('label[for="' + CSS.escape(ge.id) + '"]');
                    if (lbl) optLabel = lbl.textContent.trim();
                }
                if (optLabel) groupOptions.push(optLabel);
            });
            descriptor.options = groupOptions.length > 0 ? groupOptions : null;

            // For radio groups, try to find a group-level label
            // (often a <legend> or a label before the group)
            const fieldset = el.closest('fieldset');
            if (fieldset) {
                const legend = fieldset.querySelector('legend');
                if (legend) groupLabel = legend.textContent.trim();
            }
            descriptor.label = groupLabel;
        }

        fields.push(descriptor);
    });

    return fields;
}"""


def normalize_label(label: str) -> str:
    """Strip required-field markers (* or Pflichtfeld) and normalize whitespace."""
    label = label.replace("*", "")
    label = re.sub(r"\s+", " ", label).strip()
    # Remove trailing "Pflichtfeld" marker some forms append
    label = re.sub(r"\s*Pflichtfeld\s*$", "", label).strip()
    return label


async def extract_fields(page) -> list[dict]:
    """Extract all form fields from the current page using JavaScript.

    Returns a list of raw field descriptors (no element IDs).
    """
    raw_fields = await page.evaluate(EXTRACT_FIELDS_JS)

    # Post-process: normalize labels
    for field in raw_fields:
        field["label"] = normalize_label(field.get("label", ""))

    return raw_fields


async def extract_page_context(page) -> dict:
    """Extract additional page context for LLM interpretation."""
    return await page.evaluate("""() => {
        // Page title / heading
        const h1 = document.querySelector('h1, h2, .page-title, .form-title');
        const title = h1 ? h1.textContent.trim() : document.title;

        // Step indicator if present
        const stepEl = document.querySelector(
            '.step-indicator, .breadcrumb, .wizard-steps, [class*="step"]'
        );
        const stepText = stepEl ? stepEl.textContent.trim() : null;

        // Any visible validation messages
        const errors = Array.from(
            document.querySelectorAll('.error, .validation-error, .alert-danger, [class*="error"]')
        ).map(e => e.textContent.trim()).filter(Boolean);

        // Section headings
        const headings = Array.from(
            document.querySelectorAll('h2, h3, h4, legend, .section-title')
        ).map(h => h.textContent.trim()).filter(Boolean);

        return { title, stepText, errors, headings };
    }""")
