"""Navigation helpers for form exploration.

Handles:
- Minimal field filling to pass validation (uses Playwright native methods for Wicket compat)
- Iterative fill loop to handle cascading conditional fields
- Clicking "Weiter" and verifying navigation with structured error detection
- Page fingerprinting for step change detection
- Replaying steps to reach a specific point in a stateful form
"""

import logging
import re

logger = logging.getLogger(__name__)

# Placeholder options to skip when filling selects
_SELECT_SKIP_TEXTS = [
    "bitte wählen", "bitte waehlen", "bitte auswählen", "bitte auswaehlen",
    "-- auswahl --", "please select", "auswählen", "",
]

# JS to scan for all currently visible, empty, required fields
_SCAN_EMPTY_REQUIRED_JS = """() => {
    const fields = [];
    document.querySelectorAll('input:not([type=hidden]), select, textarea').forEach(el => {
        // Skip invisible (but allow radios/checkboxes which may have offsetParent=null)
        if (el.offsetParent === null && el.type !== 'checkbox' && el.type !== 'radio') return;
        if (el.disabled) return;

        const isRequired = el.required || el.getAttribute('aria-required') === 'true';
        if (!isRequired) return;

        // Skip if already has a value
        if (el.type === 'checkbox') {
            if (el.checked) return;
        } else if (el.type === 'radio') {
            if (el.name) {
                const group = document.querySelectorAll('input[name="' + CSS.escape(el.name) + '"]');
                if (Array.from(group).some(r => r.checked)) return;
            } else if (el.checked) return;
        } else if (el.tagName === 'SELECT') {
            const skip = ['bitte wählen', 'bitte auswählen', '-- auswahl --', ''];
            const selText = el.options[el.selectedIndex] ? el.options[el.selectedIndex].text.toLowerCase().trim() : '';
            if (el.value && !skip.includes(selText)) return;
        } else {
            if (el.value.trim()) return;
        }

        // Resolve label
        let label = '';
        if (el.id) {
            const lbl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
            if (lbl) label = lbl.textContent.replace(/\\*/g, '').trim();
        }
        if (!label) {
            const closest = el.closest('label');
            if (closest) label = closest.textContent.replace(/\\*/g, '').trim();
        }

        const options = el.tagName === 'SELECT'
            ? Array.from(el.options).map(o => ({value: o.value, text: o.textContent.trim()}))
            : null;

        fields.push({
            label: label || el.name || '',
            type: el.tagName === 'SELECT' ? 'select' : el.type,
            id: el.id,
            name: el.name,
            options: options
        });
    });
    return fields;
}"""

# JS to scan ALL fields (required or not) for checkbox consent patterns
_SCAN_CONSENT_CHECKBOXES_JS = """() => {
    const fields = [];
    document.querySelectorAll('input[type="checkbox"]').forEach(el => {
        if (el.checked) return;
        if (el.disabled) return;

        let label = '';
        if (el.id) {
            const lbl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
            if (lbl) label = lbl.textContent.replace(/\\*/g, '').trim();
        }
        if (!label) {
            const closest = el.closest('label');
            if (closest) label = closest.textContent.replace(/\\*/g, '').trim();
        }

        const combined = ((label || '') + ' ' + (el.name || '')).toLowerCase();
        const consentKws = ['datenschutz', 'einverstanden', 'gelesen', 'zustimm', 'akzeptier',
                           'erklaer', 'versicher', 'bestaetig', 'bestätig', 'pflicht',
                           'hiermit', 'kenntnisnahme', 'richtigkeit'];
        if (consentKws.some(kw => combined.includes(kw)) || el.required || el.getAttribute('aria-required') === 'true') {
            fields.push({
                label: label || el.name || 'checkbox',
                type: 'checkbox',
                id: el.id,
                name: el.name
            });
        }
    });
    return fields;
}"""


async def fill_for_navigation(page, timeout: int = 30000) -> list[dict]:
    """Fill required fields with minimal placeholders to pass validation.

    Uses Playwright's native .fill(), .select_option(), .check() methods
    instead of raw JavaScript — this triggers Wicket's server-side event
    handlers which is required for MACH formsolutions forms.

    Runs in an iterative loop: selecting an option in a required select
    may reveal NEW required fields (conditional logic). The loop re-scans
    after each pass to catch these cascading requirements.

    Returns a list of {label, type, value/action} for replay purposes.
    """
    recipe = []

    # First pass: handle consent/declaration checkboxes (even non-required ones)
    consent_checkboxes = await page.evaluate(_SCAN_CONSENT_CHECKBOXES_JS)
    for field in consent_checkboxes:
        result = await _fill_single_field(page, field)
        if result:
            recipe.append(result)

    # Iterative fill loop: scan → fill → wait for Ajax → re-scan
    for attempt in range(3):
        empty_required = await page.evaluate(_SCAN_EMPTY_REQUIRED_JS)

        if not empty_required:
            logger.info("fill_for_navigation: all required fields filled (attempt %d)", attempt + 1)
            break

        logger.info("fill_for_navigation: attempt %d — %d empty required fields", attempt + 1, len(empty_required))

        filled_any = False
        for field in empty_required:
            result = await _fill_single_field(page, field)
            if result and result.get("action") != "error":
                recipe.append(result)
                filled_any = True

                # After select/radio changes, wait for Wicket Ajax to update the page
                # (may reveal conditional fields)
                if field["type"] in ("select", "radio"):
                    await page.wait_for_timeout(800)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=3000)
                    except Exception:
                        pass

        if not filled_any:
            logger.info("fill_for_navigation: no fields could be filled on attempt %d, stopping", attempt + 1)
            break

    return recipe


async def _fill_single_field(page, field: dict) -> dict | None:
    """Fill a single field using Playwright native methods with multi-strategy locator.

    Returns a recipe entry dict or None if the field couldn't be filled.
    """
    label = field.get("label", "")
    ftype = field.get("type", "text")

    # Build locator — try multiple strategies
    locator = None

    # Strategy 1: CSS ID selector (most reliable — direct element targeting)
    if field.get("id"):
        try:
            loc = page.locator(f"#{field['id']}")
            if await loc.count() == 1:
                locator = loc
        except Exception:
            pass

    # Strategy 2: name attribute
    if not locator and field.get("name"):
        try:
            loc = page.locator(f"[name=\"{field['name']}\"]")
            count = await loc.count()
            if count >= 1:
                locator = loc.first
        except Exception:
            pass

    # Strategy 3: Playwright get_by_label — BUT only match input/select/textarea
    # MACH formsolutions has <a class="fs-hintLink" aria-label="Hinweis zu ...">
    # which get_by_label matches BEFORE the actual input. Filter to form elements only.
    if not locator and label:
        clean_label = label.split("\n")[0].strip()
        if len(clean_label) > 3:
            try:
                # Use get_by_label but chain with CSS filter to exclude non-input elements
                loc = page.get_by_label(clean_label, exact=False)
                count = await loc.count()
                for i in range(min(count, 5)):
                    el = loc.nth(i)
                    tag = await el.evaluate("el => el.tagName.toLowerCase()")
                    if tag in ("input", "select", "textarea"):
                        locator = el
                        break
            except Exception:
                pass

    if not locator:
        logger.info("fill_for_navigation: no locator for '%s' (id=%s, name=%s)", label, field.get("id"), field.get("name"))
        return {"label": label, "action": "error", "error": "no locator"}

    try:
        if ftype == "checkbox":
            await locator.check()
            logger.info("fill_for_navigation: checked '%s'", label)
            return {"label": label, "type": "checkbox", "action": "checked", "name": field.get("name")}

        elif ftype == "radio":
            await locator.check()
            logger.info("fill_for_navigation: radio selected '%s'", label)
            return {"label": label, "type": "radio", "action": "checked", "name": field.get("name")}

        elif ftype == "file":
            # Skip file uploads — can't fill with placeholder data during exploration
            logger.info("fill_for_navigation: skipping file input '%s'", label)
            return None

        elif ftype in ("select", "select-one"):
            skip = [s.lower() for s in _SELECT_SKIP_TEXTS]
            real_opts = [
                o for o in (field.get("options") or [])
                if o["value"] and o["value"] != "-1"
                and o["text"].lower().strip() not in skip
            ]
            if real_opts:
                # Prefer "no-action" options (least likely to reveal conditional fields)
                _NO_ACTION_KEYWORDS = ["keine", "kein", "nein", "nicht", "0", "ohne"]
                no_action = [o for o in real_opts
                             if any(kw in o["text"].lower() for kw in _NO_ACTION_KEYWORDS)]
                if no_action:
                    real_opts = no_action
                # Then prefer shortest text
                real_opts.sort(key=lambda o: len(o["text"]))
                await locator.select_option(value=real_opts[0]["value"])
                logger.info("fill_for_navigation: selected '%s' → '%s'", label, real_opts[0]["text"])
                return {"label": label, "type": "select", "action": "selected",
                        "value": real_opts[0]["text"], "name": field.get("name")}
            else:
                logger.info("fill_for_navigation: no real options for select '%s'", label)
                return None

        elif ftype in ("text", "email", "tel", "url", "number"):
            value = _smart_placeholder(label, ftype, field.get("name", ""))
            await locator.fill(value)
            logger.info("fill_for_navigation: filled '%s' = '%s'", label, value)
            return {"label": label, "type": ftype, "action": "filled", "value": value, "name": field.get("name")}

        elif ftype == "textarea":
            await locator.fill("Test")
            logger.info("fill_for_navigation: filled textarea '%s'", label)
            return {"label": label, "type": "textarea", "action": "filled", "value": "Test", "name": field.get("name")}

        elif ftype == "date":
            value = "01.01.2000"
            await locator.fill(value)
            logger.info("fill_for_navigation: filled date '%s' = '%s'", label, value)
            return {"label": label, "type": "date", "action": "filled", "value": value, "name": field.get("name")}

        else:
            logger.info("fill_for_navigation: unknown type '%s' for '%s', attempting fill", ftype, label)
            await locator.fill("Test")
            return {"label": label, "type": ftype, "action": "filled", "value": "Test", "name": field.get("name")}

    except Exception as e:
        logger.info("fill_for_navigation: failed to fill '%s' (%s): %s", label, ftype, e)
        return {"label": label, "action": "error", "error": str(e)}


def _smart_placeholder(label: str, ftype: str, name: str) -> str:
    """Choose a smart placeholder value based on field label/type."""
    combined = (label + " " + name).lower()

    if ftype == "email" or "mail" in combined:
        return "test@example.com"

    # Date detection by label
    is_date = ("datum" in combined or "date" in combined
               or "tt.mm" in combined or "dd.mm" in combined
               or ("geburt" in combined and "ort" not in combined
                   and "land" not in combined and "name" not in combined))
    if is_date:
        return "01.01.2000"

    if "plz" in combined or "postleitzahl" in combined:
        return "48149"
    if ftype == "tel" or "telefon" in combined or "fax" in combined:
        return "0251000000"
    if "hausnummer" in combined:
        return "1"
    if "stunde" in combined or "hh" in combined:
        return "12"
    if "minute" in combined or "mm" in combined:
        return "00"
    if "nummer" in combined or "number" in combined:
        return "12345"

    return "Test"


async def fill_specific_values(page, recipe: list[dict], field_timeout: int = 3000) -> None:
    """Replay specific field values from a previous fill recipe using Playwright methods.

    Uses a short per-field timeout (default 3s) to fail fast on stale locators
    instead of blocking 30s per field.
    """
    for item in recipe:
        try:
            if item.get("action") in ("skipped", "error"):
                continue

            locator = None

            # Strategy 1: label-based (session-independent, preferred)
            if item.get("label"):
                clean = item["label"].split("\n")[0].strip()
                if len(clean) > 3:
                    try:
                        loc = page.get_by_label(clean, exact=False)
                        count = await loc.count()
                        if count >= 1:
                            # Filter to actual form elements (skip hint links etc.)
                            for i in range(min(count, 5)):
                                el = loc.nth(i)
                                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                                if tag in ("input", "select", "textarea"):
                                    locator = el
                                    break
                            if not locator:
                                locator = loc.first
                    except Exception:
                        pass

            # Strategy 2: name attribute — but SKIP Wicket session-scoped names
            # (they look like "components:N:component:border:..." and change every session)
            if not locator and item.get("name"):
                name = item["name"]
                if "components:" not in name and "component:" not in name:
                    try:
                        locator = page.locator(f"[name=\"{name}\"]").first
                    except Exception:
                        pass

            if not locator:
                logger.debug("fill_specific_values: no locator for '%s', skipping", item.get("label", ""))
                continue

            ftype = item.get("type", "text")

            if ftype == "checkbox":
                await locator.check(timeout=field_timeout)
            elif ftype == "select":
                if item.get("value"):
                    try:
                        await locator.select_option(label=item["value"], timeout=field_timeout)
                    except Exception:
                        await locator.select_option(value=item.get("value", ""), timeout=field_timeout)
            elif ftype == "radio":
                await locator.check(timeout=field_timeout)
            else:
                await locator.fill(item.get("value", "Test"), timeout=field_timeout)

            await page.wait_for_timeout(300)

        except Exception as e:
            logger.info("fill_specific_values: skipping '%s': %s", item.get("label", ""), e)


async def click_next_and_verify(page, timeout: int = 30000) -> dict:
    """Click Weiter and verify navigation happened.

    Returns dict with:
        navigated: bool
        validation_errors: list[str] (empty if no errors)
    """
    # Capture BEFORE state
    before = await _page_fingerprint(page)

    # Click Weiter
    clicked = await _click_next_button(page)
    if not clicked:
        return {"navigated": False, "validation_errors": ["No Weiter button found"]}

    # Wait for Wicket server-side form submission
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    await page.wait_for_timeout(1000)

    # Check for validation errors FIRST (before comparing pages)
    validation_errors = await _detect_validation_errors(page)
    if validation_errors:
        logger.info("click_next_and_verify: validation errors: %s", validation_errors[:3])
        return {"navigated": False, "validation_errors": validation_errors}

    # Capture AFTER state and compare
    after = await _page_fingerprint(page)

    if before["url"] != after["url"]:
        return {"navigated": True, "validation_errors": []}
    if before["field_labels"] != after["field_labels"]:
        return {"navigated": True, "validation_errors": []}
    if before["sub_heading"] != after["sub_heading"]:
        return {"navigated": True, "validation_errors": []}

    return {"navigated": False, "validation_errors": ["Page did not change"]}


async def _page_fingerprint(page) -> dict:
    """Capture a fingerprint of the current page for step-change detection."""
    return await page.evaluate("""() => ({
        url: location.href,
        title: document.title,
        sub_heading: (() => {
            const h = document.querySelector('h2, h3');
            return h ? h.textContent.trim() : '';
        })(),
        field_labels: (() => {
            const labels = [];
            document.querySelectorAll('input:not([type=hidden]), select, textarea').forEach(el => {
                if (el.offsetParent === null && el.type !== 'radio' && el.type !== 'checkbox') return;
                let label = '';
                if (el.id) {
                    const lbl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                    if (lbl) label = lbl.textContent.trim();
                }
                labels.push(label || el.type);
            });
            return labels.sort().join('|');
        })()
    })""")


async def _detect_validation_errors(page) -> list[str]:
    """Detect Wicket/MACH formsolutions validation errors on the current page."""
    return await page.evaluate("""() => {
        const errors = [];
        // Check page title for error indicator
        if (document.title.includes('Fehler')) {
            errors.push('Page title: ' + document.title);
        }
        // MACH formsolutions error panels
        document.querySelectorAll('.feedbackPanelERROR, .error-message, .validation-error').forEach(el => {
            const text = el.textContent.trim();
            if (text && text.length < 200) errors.push(text);
        });
        // Inline error patterns in body text
        // NOTE: "Pflichtangabe" is a static annotation on every MACH form page (= "required field"),
        // NOT a validation error. Do not match it.
        const bodyText = document.body.innerText;
        const patterns = ['Bitte tragen Sie', 'Bitte wählen Sie', 'ist erforderlich'];
        patterns.forEach(p => {
            if (bodyText.includes(p)) {
                const idx = bodyText.indexOf(p);
                const snippet = bodyText.substring(idx, idx + 100).split('.')[0];
                errors.push(snippet);
            }
        });
        return errors;
    }""")


async def _click_next_button(page) -> bool:
    """Find and click a Weiter/Next button."""
    patterns = ["Weiter", "weiter", "Nächster Schritt", "Naechster Schritt", "Next"]

    for pattern in patterns:
        try:
            btn = page.get_by_role("button", name=pattern)
            if await btn.count() > 0:
                await btn.first.click()
                return True
        except Exception:
            pass
        try:
            link = page.get_by_role("link", name=pattern)
            if await link.count() > 0:
                await link.first.click()
                return True
        except Exception:
            pass

    # JS fallback
    clicked = await page.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll(
            'button, input[type="submit"], input[type="button"], a.btn'
        ));
        const next = btns.find(b => {
            const text = (b.textContent || b.value || '').toLowerCase();
            return text.includes('weiter') || text.includes('next')
                || text.includes('nächster') || text.includes('naechster');
        });
        if (next) { next.click(); return true; }
        return false;
    }""")
    return clicked


async def get_page_signature(page) -> str:
    """Get a signature of the current page for loop detection (sub-headings + field labels)."""
    fp = await _page_fingerprint(page)
    return fp["sub_heading"] + "|" + fp["field_labels"]
