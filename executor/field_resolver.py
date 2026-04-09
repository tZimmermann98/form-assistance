"""Label-based field resolution for the deterministic executor.

Finds form fields by label text, NOT by element ID.
Three resolution strategies with automatic fallback.
Optional section-scoped search for disambiguating duplicate labels.
"""

import logging
import re

logger = logging.getLogger(__name__)


def normalize_label(label: str) -> str:
    """Strip required-field markers and normalize whitespace."""
    label = label.replace("*", "")
    label = re.sub(r"\s+", " ", label).strip()
    label = re.sub(r"\s*Pflichtfeld\s*$", "", label).strip()
    return label


class FieldResolver:
    """Finds form fields by label text, not by element ID."""

    async def find_field(self, page, label: str, field_type: str, section_name: str = None):
        """Find a field by its label text, optionally scoped to a section.

        Strategy:
        0. (if section_name) Scope search within the section's DOM container
        1. page.get_by_label() — Playwright's built-in label matching
        2. JS: find label containing text, resolve for= attribute
        3. JS: find label containing text, find input in same parent

        Returns the Playwright Locator or None if not found.
        """
        normalized = normalize_label(label)

        # Strategy 0: Section-scoped search (if section name provided)
        if section_name:
            locator = await self._try_section_scoped(page, normalized, field_type, section_name)
            if locator:
                return locator

        # Strategy 1: Playwright native get_by_label
        locator = await self._try_get_by_label(page, normalized, field_type)
        if locator:
            return locator

        # Strategy 2: JS label[for] resolution
        locator = await self._try_js_label_for(page, normalized, field_type)
        if locator:
            return locator

        # Strategy 3: Parent container traversal
        locator = await self._try_parent_traversal(page, normalized, field_type)
        if locator:
            return locator

        logger.warning("Could not find field: '%s' (type: %s)", label, field_type)
        return None

    async def _try_section_scoped(self, page, label: str, field_type: str, section_name: str):
        """Strategy 0: Search within a section's DOM container."""
        try:
            # MACH formsolutions uses various heading patterns for sections
            section_selectors = [
                f"fieldset:has(legend:has-text('{section_name}'))",
                f"div:has(> h2:has-text('{section_name}'))",
                f"div:has(> h3:has-text('{section_name}'))",
                f"div:has(> h4:has-text('{section_name}'))",
                f"section:has(> h2:has-text('{section_name}'))",
                f"section:has(> h3:has-text('{section_name}'))",
            ]
            for sel in section_selectors:
                section_el = page.locator(sel)
                if await section_el.count() > 0:
                    scoped = section_el.first.get_by_label(label, exact=False)
                    count = await scoped.count()
                    if count == 1:
                        return scoped
                    elif count > 1 and field_type in ("radio", "checkbox"):
                        return scoped.first
        except Exception:
            pass
        return None

    async def _try_get_by_label(self, page, label: str, field_type: str):
        """Strategy 1: Playwright's built-in label matching."""
        try:
            locator = page.get_by_label(label, exact=False)
            count = await locator.count()
            if count == 1:
                return locator
            elif count > 1:
                # For radios/checkboxes, multiple is expected — return first
                if field_type in ("radio", "checkbox"):
                    return locator.first
                # For others, try exact match
                exact = page.get_by_label(label, exact=True)
                if await exact.count() == 1:
                    return exact
        except Exception:
            pass
        return None

    async def _try_js_label_for(self, page, label: str, field_type: str):
        """Strategy 2: JavaScript label[for] resolution."""
        try:
            found = await page.evaluate("""(labelText) => {
                const labels = Array.from(document.querySelectorAll('label'));
                const match = labels.find(l =>
                    l.textContent.replace(/\\*/g, '').replace(/\\s+/g, ' ').trim()
                        .includes(labelText)
                );
                if (match && match.htmlFor) {
                    const input = document.getElementById(match.htmlFor);
                    if (input) return match.htmlFor;
                }
                return null;
            }""", label)

            if found:
                locator = page.locator(f"#{found}")
                if await locator.count() == 1:
                    return locator
        except Exception:
            pass
        return None

    async def _try_parent_traversal(self, page, label: str, field_type: str):
        """Strategy 3: Find label, then input within same container."""
        try:
            tag = _type_to_tag(field_type)
            # Look for label text, then find adjacent or child input
            selectors = [
                f"label:has-text('{label}') + {tag}",
                f"label:has-text('{label}') ~ {tag}",
                f":has(> label:has-text('{label}')) {tag}",
                f":has(> label:has-text('{label}')) input",
                f":has(> label:has-text('{label}')) select",
                f":has(> label:has-text('{label}')) textarea",
            ]
            for selector in selectors:
                try:
                    locator = page.locator(selector).first
                    if await locator.count() >= 1:
                        return locator
                except Exception:
                    continue
        except Exception:
            pass
        return None


def _type_to_tag(field_type: str) -> str:
    """Map field type to HTML tag for CSS selectors."""
    if field_type == "select":
        return "select"
    if field_type == "textarea":
        return "textarea"
    return "input"
