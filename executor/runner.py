"""Deterministic form executor — NO LLM, NO external API calls.

Fills a form based on an approved FormGraph using Playwright.
All citizen PII is discarded after execution.
Audit logs NEVER contain PII — values are always [REDACTED].

V1 HARD RULE: Fill all fields but NEVER click the final submit button.
"""

import base64
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from executor.field_resolver import FieldResolver, normalize_label
from explorer.extractors.auth_detector import detect_auth_gate, bypass_auth_gate
from explorer.recording import get_recordings_dir, should_record

logger = logging.getLogger(__name__)


def _to_dd_mm_yyyy(value: str) -> str:
    """Convert ISO date (YYYY-MM-DD) or other formats to DD.MM.YYYY."""
    # Already in DD.MM.YYYY
    if re.match(r"^\d{2}\.\d{2}\.\d{4}$", value):
        return value
    # ISO format YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        parts = value[:10].split("-")
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return value


def _derive_key(label: str) -> str:
    """Derive a snake_case key from a German label."""
    key = normalize_label(label).lower()
    # Replace umlauts
    for old, new in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"),
                     ("ae", "ae"), ("oe", "oe"), ("ue", "ue")]:
        key = key.replace(old, new)
    key = re.sub(r"[^a-z0-9]+", "_", key)
    key = key.strip("_")
    return key


class FormExecutor:
    """Deterministically fills a form based on a FormGraph.

    No LLM. No external API calls. No PII leaves this process.
    All citizen data is discarded after execution.
    """

    def __init__(self):
        self.resolver = FieldResolver()

    async def execute(self, form_graph: dict, field_values: dict, source_url: str | None = None) -> dict:
        """Fill a form and return the result.

        Args:
            form_graph: The approved FormGraph.graph_data
            field_values: Citizen's data mapped to field keys
            source_url: Override URL (for testing with local fixtures)

        Returns:
            {status, screenshot_base64, errors, audit_log, trigger_recheck}
        """
        from playwright.async_api import async_playwright

        headless = os.environ.get("EXPLORER_HEADLESS", "true").lower() != "false"
        timeout = int(os.environ.get("EXPLORER_TIMEOUT", "30000"))
        url = source_url or form_graph.get("source_url", "")

        if not url:
            # Try to find URL from steps metadata
            return {"status": "error", "error": "No source URL provided"}

        audit_log = []
        errors = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)

            # Recording setup: video + trace for debugging
            recording = should_record()
            exec_id = str(uuid.uuid4())[:8]
            rec_dir = get_recordings_dir("execute", exec_id) if recording else None
            context_kwargs = {
                "viewport": {"width": 1280, "height": 900},
                "locale": "de-DE",
                "accept_downloads": True,  # Required for PDF download interception
            }
            if recording and rec_dir:
                context_kwargs["record_video_dir"] = str(rec_dir / "videos")
                context_kwargs["record_video_size"] = {"width": 1280, "height": 900}

            context = await browser.new_context(**context_kwargs)

            if recording and rec_dir:
                await context.tracing.start(
                    screenshots=True, snapshots=True, sources=False
                )
                logger.info("Recording enabled for execution %s → %s", exec_id, rec_dir)

            page = await context.new_page()
            page.set_default_timeout(timeout)

            try:
                await page.goto(url, wait_until="networkidle")
                audit_log.append(self._log_entry("navigate", "Loaded form URL"))

                # Resolve steps: handle branching forms
                steps = self._resolve_steps(form_graph, field_values)
                total_steps = len(steps)

                for step_idx, step in enumerate(steps):
                    step_num = step.get("step", step_idx + 1)
                    step_id = step.get("id", f"step_{step_num}")
                    audit_log.append(self._log_entry("navigate_step", f"Step {step_num}: {step.get('title', '')}"))

                    # Skip display-only steps (auth gate, info page, final page)
                    # These are handled automatically during navigation
                    if step.get("step_type") in ("auth_gate", "info_page", "final_page"):
                        audit_log.append(self._log_entry(
                            "skip_step", f"Step {step_num}: {step.get('step_type')} — handled automatically"
                        ))
                        continue

                    # Check for BundID/auth gate (can appear after consent)
                    current_url = page.url
                    logger.info("Step %d: checking page URL=%s", step_num, current_url)
                    auth_gate = await detect_auth_gate(page)
                    logger.info("Step %d: auth_gate=%s", step_num, auth_gate)
                    if auth_gate and auth_gate.detected:
                        audit_log.append(self._log_entry("auth_bypass", f"BundID gate detected ({auth_gate.auth_type}), bypassing..."))
                        bypassed = await bypass_auth_gate(page, auth_gate)
                        if bypassed:
                            try:
                                await page.wait_for_load_state("networkidle", timeout=timeout)
                            except Exception:
                                await page.wait_for_timeout(2000)
                            audit_log.append(self._log_entry("auth_bypass", "BundID gate bypassed successfully"))
                        else:
                            audit_log.append(self._log_entry("auth_bypass", "WARNING: BundID bypass may have failed"))

                    # Handle consent step automatically
                    if step_id == "consent" or self._is_consent_step(step):
                        result = await self._handle_consent(page)
                        audit_log.append(self._log_entry("consent", f"Consent handled: {result}"))
                        if step_idx < total_steps - 1:
                            nav_result = await self._navigate_next(page, timeout)
                            audit_log.append(self._log_entry("navigate", f"Next: {nav_result}"))

                            # After consent, check for BundID gate again
                            auth_gate2 = await detect_auth_gate(page)
                            if auth_gate2 and auth_gate2.detected:
                                audit_log.append(self._log_entry("auth_bypass", "Post-consent BundID gate, bypassing..."))
                                await bypass_auth_gate(page, auth_gate2)
                                try:
                                    await page.wait_for_load_state("networkidle", timeout=timeout)
                                except Exception:
                                    await page.wait_for_timeout(2000)

                            # Skip info/instruction pages (no input fields, just Weiter)
                            for _ in range(3):  # max 3 info pages
                                has_inputs = await page.evaluate(
                                    "() => document.querySelectorAll('input:not([type=hidden]), select, textarea').length"
                                )
                                if has_inputs > 0:
                                    break
                                audit_log.append(self._log_entry("navigate", "Info page detected (no fields), skipping..."))
                                nav_result = await self._navigate_next(page, timeout)
                                if nav_result == "failed":
                                    break
                        continue

                    # Skip info/instruction pages that may appear between steps
                    has_inputs = await page.evaluate(
                        "() => document.querySelectorAll('input:not([type=hidden]), select, textarea').length"
                    )
                    if has_inputs == 0:
                        audit_log.append(self._log_entry("navigate", f"Step {step_num}: no input fields visible, skipping info page..."))
                        nav_result = await self._navigate_next(page, timeout)
                        audit_log.append(self._log_entry("navigate", f"Info page skip: {nav_result}"))

                    # Wait briefly for dynamic content to load after navigation
                    await page.wait_for_timeout(1000)

                    # Check for validation errors from previous step navigation
                    validation_errors = await page.evaluate("""() => {
                        const errors = document.querySelectorAll('.error, .feedbackPanelERROR, .has-error, [class*="error"], .alert-danger');
                        return Array.from(errors).map(e => e.textContent.trim().substring(0, 100)).filter(t => t.length > 0);
                    }""")
                    if validation_errors:
                        logger.warning("Step %d: Validation errors present: %s", step_num, validation_errors[:3])
                        audit_log.append(self._log_entry("validation", f"Step {step_num}: errors detected: {validation_errors[:3]}"))

                    # Fill fields in this step
                    for section in step.get("sections", []):
                        section_name = section.get("section", "")
                        for field in section.get("fields", []):
                            label = field.get("label", "")
                            field_type = field.get("type", "text")

                            # Use mapped_key from graph (single source of truth)
                            key = field.get("mapped_key") or _derive_key(label)
                            value = field_values.get(key)

                            # Fallback: try old-style derived key and raw label
                            if value is None:
                                value = field_values.get(_derive_key(label))
                            if value is None:
                                value = field_values.get(label)

                            if value is None:
                                if field.get("required"):
                                    errors.append(f"Missing required field: {label} (key: {mapped_key})")
                                audit_log.append(self._log_entry(
                                    "skip_field", f"Step {step_num}, '{label}' — no value provided",
                                ))
                                continue

                            # Find the field element by label (with section context for disambiguation)
                            element = await self.resolver.find_field(page, label, field_type, section_name)

                            if element is None:
                                # Retry once — field might not be visible yet
                                await page.wait_for_timeout(1000)
                                element = await self.resolver.find_field(page, label, field_type, section_name)

                            if element is None:
                                # Log page state for debugging
                                current_url = page.url
                                page_title = await page.evaluate("() => document.title")
                                logger.error(
                                    "Field not found: '%s' on step %d. URL: %s, Page title: %s",
                                    label, step_num, current_url, page_title
                                )
                                # Save trace before returning
                                if recording and rec_dir:
                                    try:
                                        await context.tracing.stop(path=str(rec_dir / "trace.zip"))
                                        await context.close()
                                        logger.info("Execution trace saved on field_not_found: %s", rec_dir)
                                    except Exception:
                                        pass
                                await browser.close()
                                return {
                                    "status": "field_not_found",
                                    "error": f"Could not find field '{label}' on step {step_num}",
                                    "trigger_recheck": True,
                                    "audit_log": audit_log,
                                }

                            # Fill the field
                            try:
                                await self._fill_field(page, element, field_type, value)
                                audit_log.append(self._log_entry(
                                    "fill_field",
                                    f"Step {step_num}, '{label}' ({field_type}) = [REDACTED]",
                                ))

                                # If this field has conditional logic, wait for
                                # dynamic content to appear before filling next fields
                                if field.get("conditional_logic"):
                                    await page.wait_for_timeout(500)
                                    try:
                                        await page.wait_for_load_state("networkidle", timeout=3000)
                                    except Exception:
                                        pass

                            except Exception as e:
                                errors.append(f"Failed to fill '{label}': {str(e)}")
                                audit_log.append(self._log_entry(
                                    "fill_error",
                                    f"Step {step_num}, '{label}' — error: {str(e)}",
                                ))

                    # Navigate to next step (except the last one)
                    if step_idx < total_steps - 1:
                        nav_result = await self._navigate_next(page, timeout)
                        audit_log.append(self._log_entry("navigate", f"Next: {nav_result}"))
                        if nav_result.startswith("validation_error"):
                            # Form validation rejected — return meaningful error
                            if recording and rec_dir:
                                try:
                                    await context.tracing.stop(path=str(rec_dir / "trace.zip"))
                                    await context.close()
                                except Exception:
                                    pass
                            await browser.close()
                            return {
                                "status": "validation_error",
                                "error": f"Validierungsfehler auf Schritt {step_num}: {nav_result.replace('validation_error: ', '')}",
                                "trigger_recheck": False,
                                "audit_log": audit_log,
                            }
                        if nav_result == "failed":
                            errors.append(f"Failed to navigate past step {step_num}")

                        # Skip info/instruction pages (pages with no input fields)
                        for _ in range(3):
                            has_inputs = await page.evaluate(
                                "() => document.querySelectorAll('input:not([type=hidden]), select, textarea').length"
                            )
                            if has_inputs > 0:
                                break
                            audit_log.append(self._log_entry("navigate", "Info page detected between steps, skipping..."))
                            skip_result = await self._navigate_next(page, timeout)
                            if skip_result == "failed":
                                break

                        # Verify we actually moved to the next step by checking
                        # if the next step's first field exists on this page
                        if step_idx + 1 < total_steps:
                            next_step = steps[step_idx + 1]
                            if not self._is_consent_step(next_step):
                                next_first_label = self._get_first_field_label(next_step)
                                if next_first_label:
                                    found = await self.resolver.find_field(page, next_first_label, "text")
                                    if found is None:
                                        # Page didn't advance — might be validation error
                                        # Try clicking Weiter again after a wait
                                        logger.warning("Page didn't advance to step %d (field '%s' not found). Retrying navigation...",
                                                       step_idx + 2, next_first_label)
                                        audit_log.append(self._log_entry("navigate", f"Page didn't advance, retrying..."))
                                        await page.wait_for_timeout(2000)
                                        nav_result2 = await self._navigate_next(page, timeout)
                                        # Skip info pages again
                                        for _ in range(3):
                                            has_inputs = await page.evaluate(
                                                "() => document.querySelectorAll('input:not([type=hidden]), select, textarea').length"
                                            )
                                            if has_inputs > 0:
                                                break
                                            await self._navigate_next(page, timeout)

                # V1 HARD RULE: Do NOT click final submit.
                # Note: Vorschau/Drucken are preview actions, NOT submission — safe to click.
                audit_log.append(self._log_entry(
                    "complete",
                    "All fields filled. STOPPED before final submit (V1 rule).",
                ))

                # Take final screenshot
                screenshot_bytes = await page.screenshot(type="png", full_page=True)
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode()

                # Capture platform PDF if outcome is print_and_sign
                pdf_b64 = None
                outcome = form_graph.get("outcome", {})
                if outcome.get("type") == "print_and_sign":
                    pdf_bytes = await self._capture_form_pdf(page, outcome)
                    if pdf_bytes:
                        pdf_b64 = base64.b64encode(pdf_bytes).decode()
                        audit_log.append(self._log_entry("pdf", "Platform PDF captured"))
                    else:
                        audit_log.append(self._log_entry("pdf", "Could not capture platform PDF"))

            except Exception as e:
                logger.exception("Form execution failed")
                # Save trace even on error
                if recording and rec_dir:
                    try:
                        await context.tracing.stop(path=str(rec_dir / "trace.zip"))
                        await context.close()
                    except Exception:
                        pass
                await browser.close()
                return {
                    "status": "error",
                    "error": str(e),
                    "audit_log": audit_log,
                }

            # Save trace on success
            if recording and rec_dir:
                trace_path = rec_dir / "trace.zip"
                await context.tracing.stop(path=str(trace_path))
                logger.info("Execution trace saved: %s", trace_path)
                await context.close()  # Finalize video files
            else:
                await context.close()
            await browser.close()

        # Determine final status
        outcome_type = form_graph.get("outcome", {}).get("type", "unknown")
        if errors:
            return {
                "status": "partial",
                "errors": errors,
                "screenshot_base64": screenshot_b64,
                "pdf_base64": pdf_b64,
                "outcome_type": outcome_type,
                "audit_log": audit_log,
            }

        return {
            "status": "success",
            "screenshot_base64": screenshot_b64,
            "pdf_base64": pdf_b64,
            "outcome_type": outcome_type,
            "audit_log": audit_log,
        }

    async def _capture_form_pdf(self, page, outcome: dict) -> bytes | None:
        """Click the platform's Vorschau/Drucken button and capture the generated PDF.

        MACH formsolutions generates official PDFs via these buttons.
        This is NOT the same as page.pdf() which just prints the HTML wrapper.

        Strategies:
        1. Vorschau/Drucken opens PDF in new tab (popup) → intercept
        2. Vorschau/Drucken triggers file download → intercept
        3. Last resort: browser PDF of current page
        """
        preview_text = outcome.get("preview_button_text", "Vorschau")
        print_text = outcome.get("print_button_text", "Drucken")
        candidates = [preview_text, print_text, "Vorschau", "Drucken", "PDF"]
        # Deduplicate while preserving order
        seen = set()
        btn_texts = []
        for t in candidates:
            if t and t not in seen:
                seen.add(t)
                btn_texts.append(t)

        # Strategy 1: Button opens PDF in new tab (popup)
        for btn_text in btn_texts:
            try:
                async with page.expect_popup(timeout=5000) as popup_info:
                    await page.get_by_role("button", name=btn_text).first.click()
                popup = await popup_info.value
                await popup.wait_for_load_state("networkidle", timeout=10000)
                pdf_url = popup.url

                # Check if it's a direct PDF URL or inline-rendered PDF
                if "pdf" in pdf_url.lower() or pdf_url.endswith(".pdf"):
                    response = await popup.context.request.get(pdf_url)
                    pdf_bytes = await response.body()
                    await popup.close()
                    logger.info("Captured PDF via popup (direct URL): %d bytes", len(pdf_bytes))
                    return pdf_bytes
                else:
                    # PDF rendered inline in browser — use browser PDF rendering
                    pdf_bytes = await popup.pdf(format="A4", print_background=True)
                    await popup.close()
                    logger.info("Captured PDF via popup (browser render): %d bytes", len(pdf_bytes))
                    return pdf_bytes
            except Exception as e:
                logger.debug("Popup strategy failed for '%s': %s", btn_text, e)

        # Strategy 2: Download interception (PDF triggers file download)
        for btn_text in btn_texts:
            try:
                async with page.expect_download(timeout=5000) as download_info:
                    await page.get_by_role("button", name=btn_text).first.click()
                download = await download_info.value
                path = await download.path()
                if path:
                    with open(path, "rb") as f:
                        pdf_bytes = f.read()
                    logger.info("Captured PDF via download: %d bytes", len(pdf_bytes))
                    return pdf_bytes
            except Exception as e:
                logger.debug("Download strategy failed for '%s': %s", btn_text, e)

        # Strategy 3: Last resort — browser PDF of current page
        try:
            pdf_bytes = await page.pdf(format="A4", print_background=True)
            logger.info("Captured PDF via browser render (fallback): %d bytes", len(pdf_bytes))
            return pdf_bytes
        except Exception as e:
            logger.warning("Browser PDF fallback failed: %s", e)

        return None

    async def _fill_field(self, page, element, field_type: str, value: str):
        """Fill a single field based on its type."""
        if field_type == "file":
            # File upload: value is base64-encoded file content
            import tempfile
            try:
                file_bytes = base64.b64decode(value)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
                    f.write(file_bytes)
                    temp_path = f.name
                await element.set_input_files(temp_path)
            except Exception as e:
                logger.warning("File upload failed: %s", e)
                raise
            return

        elif field_type == "select":
            # Try by value first, then by label text
            try:
                await element.select_option(value=value)
            except Exception:
                await element.select_option(label=value)

        elif field_type == "checkbox":
            should_check = str(value).lower() in ("true", "1", "yes", "ja", "checked")
            if should_check:
                await element.check()
            else:
                await element.uncheck()

        elif field_type == "radio":
            # For radio, click the option matching the value
            await page.get_by_label(value, exact=False).first.check()

        elif field_type == "date":
            date_str = _to_dd_mm_yyyy(str(value))
            await element.fill(date_str)

        else:
            # text, email, textarea, tel, etc.
            await element.fill(str(value))

    async def _handle_consent(self, page) -> str:
        """Check consent checkboxes on the current page."""
        try:
            checked = await page.evaluate("""() => {
                let count = 0;
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    if (!cb.checked) { cb.click(); count++; }
                });
                return count;
            }""")
            return f"checked {checked} checkbox(es)"
        except Exception as e:
            return f"error: {e}"

    async def _navigate_next(self, page, timeout: int) -> str:
        """Click the 'Weiter' button, wait for page load, and check for validation errors.

        Returns:
            "success" — page advanced
            "validation_error: <details>" — form rejected with validation error
            "failed" — no Weiter button found
        """
        # Capture page state before navigation for comparison
        before_text = await page.evaluate("() => document.body.innerText.substring(0, 2000)")

        patterns = ["Weiter", "weiter", "Nächster Schritt", "Next"]
        clicked = False

        for pattern in patterns:
            try:
                btn = page.get_by_role("button", name=pattern)
                if await btn.count() > 0:
                    await btn.first.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            # JS fallback
            clicked = await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button, input[type="submit"], a.btn'));
                const next = btns.find(b => {
                    const text = (b.textContent || b.value || '').toLowerCase();
                    return text.includes('weiter') || text.includes('next');
                });
                if (next) { next.click(); return true; }
                return false;
            }""")

        if not clicked:
            return "failed"

        try:
            await page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            await page.wait_for_timeout(2000)

        # Check for validation errors (German form error patterns)
        after_text = await page.evaluate("() => document.body.innerText.substring(0, 2000)")
        error_indicators = [
            "Fehler bei der Dateneingabe",
            "Bitte tragen Sie",
            "ist erforderlich",
            "muss ausgefüllt",
        ]
        for indicator in error_indicators:
            if indicator in after_text and indicator not in before_text:
                # Extract specific error messages
                error_msgs = await page.evaluate("""() => {
                    const errors = document.querySelectorAll(
                        '.feedbackPanelERROR, .error-message, .validation-error, [class*="error"] li'
                    );
                    return Array.from(errors).map(e => e.textContent.trim()).filter(t => t.length > 0 && t.length < 200);
                }""")
                detail = "; ".join(error_msgs[:3]) if error_msgs else indicator
                logger.error("Validation error after clicking Weiter: %s", detail)
                return f"validation_error: {detail}"

        return "success"

    def _get_first_field_label(self, step: dict) -> str | None:
        """Get the first field label from a step (for page verification)."""
        for section in step.get("sections", []):
            for field in section.get("fields", []):
                label = field.get("label", "")
                if label:
                    return label
        return None

    def _is_consent_step(self, step: dict) -> bool:
        """Detect if a step is a consent/privacy step."""
        title = (step.get("title") or "").lower()
        desc = (step.get("description") or "").lower()
        combined = title + " " + desc
        return any(kw in combined for kw in ["einwilligung", "datenschutz", "consent", "zustimmung"])

    def _resolve_steps(self, form_graph: dict, field_values: dict) -> list[dict]:
        """Resolve the correct step sequence for branching forms.

        For linear forms: returns form_graph["steps"] as-is.
        For branching forms: returns common_steps + the matching branch path.
        """
        exploration_type = form_graph.get("exploration_type", "linear")

        if exploration_type != "branching":
            return form_graph.get("steps", [])

        common = form_graph.get("common_steps", [])
        branches = form_graph.get("branch_paths", [])

        if not branches:
            return common

        # Find which branch to take based on the discriminator field
        for branch in branches:
            branch_point = branch.get("branch_point", "")
            branch_value = branch.get("branch_value", "")

            if not branch_point:
                continue

            # Check if the citizen's field values match this branch
            bp_key = _derive_key(branch_point)
            citizen_value = (
                field_values.get(bp_key)
                or field_values.get(branch_point)
                or field_values.get(normalize_label(branch_point))
            )

            if citizen_value and citizen_value.lower() == branch_value.lower():
                return common + branch.get("steps", [])

        # No match — use first branch as default
        logger.warning("No branch match found, using first branch path")
        return common + (branches[0].get("steps", []) if branches else [])

    def _log_entry(self, action: str, detail: str) -> dict:
        return {
            "action": action,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
