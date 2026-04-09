"""Form exploration agent.

Two modes:
- Real: Playwright + LLM exploration of live forms
- Mock: Simulated exploration using reference data (for tests/demos)

Controlled by EXPLORER_MODE env var (real|mock), defaults to real.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from explorer.recording import get_recordings_dir, should_record

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import async_session
from backend.app.models.exploration_job import ExplorationJob, JobStatus
from backend.app.models.form_graph import FormGraph, FormStatus
from backend.app.services.llm_client import LLMClient, LLMConfig
from explorer.extractors.auth_detector import detect_auth_gate, bypass_auth_gate
from explorer.extractors.branch_detector import find_branch_points, branches_to_conditional_logic
from explorer.extractors.field_extractor import extract_fields, extract_page_context
from explorer.llm.prompts import (
    SYSTEM_PROMPT,
    OUTCOME_DETECTION_PROMPT,
    format_step_prompt,
    format_mcp_spec_prompt,
)

logger = logging.getLogger(__name__)


# ── Progress logging helper ──────────────────────────────────────────────

async def _append_log(session: AsyncSession, job_id: UUID, step: int, message: str):
    """Append a progress log entry to the job."""
    result = await session.execute(
        select(ExplorationJob).where(ExplorationJob.id == job_id)
    )
    job = result.scalar_one()
    log = list(job.progress_log or [])
    log.append({
        "step": step,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    job.progress_log = log
    await session.commit()


# ═══════════════════════════════════════════════════════════════════════════
#  REAL EXPLORER
# ═══════════════════════════════════════════════════════════════════════════

async def _find_next_button(page) -> bool:
    """Try to find and click a 'Weiter' / 'Next' button. Returns True if found."""
    # Common patterns for German form navigation buttons
    button_patterns = [
        "Weiter",
        "weiter",
        "Nächster Schritt",
        "Naechster Schritt",
        "Next",
    ]

    for pattern in button_patterns:
        try:
            # Try button/input with exact or contained text
            btn = page.get_by_role("button", name=pattern)
            if await btn.count() > 0:
                await btn.first.click()
                return True
        except Exception:
            pass

        try:
            btn = page.get_by_role("link", name=pattern)
            if await btn.count() > 0:
                await btn.first.click()
                return True
        except Exception:
            pass

    # Fallback: JS search for submit-like buttons
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


async def _handle_consent_step(page) -> bool:
    """Check if the current page is a consent/privacy step and handle it.

    Returns True if a consent step was handled.
    """
    # Look for consent checkbox pattern
    has_consent = await page.evaluate("""() => {
        const checkboxes = document.querySelectorAll('input[type="checkbox"]');
        const text = document.body.innerText.toLowerCase();
        const hasPrivacyText = text.includes('datenschutz') || text.includes('einwilligung')
            || text.includes('einverstanden') || text.includes('zustimm');
        return checkboxes.length > 0 && checkboxes.length <= 2 && hasPrivacyText;
    }""")

    if has_consent:
        # Check all consent checkboxes
        await page.evaluate("""() => {
            document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                if (!cb.checked) cb.click();
            });
        }""")
        await page.wait_for_timeout(300)
        return True

    return False


async def run_real_exploration(job_id: UUID, llm_config: LLMConfig):
    """Run the real Playwright + LLM exploration pipeline.

    Uses tree-based exploration to discover all form paths,
    then compiles the tree into a graph with LLM interpretation.
    """
    from playwright.async_api import async_playwright
    from explorer.tree_explorer import explore_tree

    headless = os.environ.get("EXPLORER_HEADLESS", "true").lower() != "false"
    timeout = int(os.environ.get("EXPLORER_TIMEOUT", "30000"))

    llm = LLMClient(llm_config)

    async with async_session() as session:
        result = await session.execute(
            select(ExplorationJob).where(ExplorationJob.id == job_id)
        )
        job = result.scalar_one()
        source_url = job.source_url
        form_graph_id = job.form_graph_id

        job.status = JobStatus.RUNNING
        job.progress_log = []
        await session.commit()

        log_step = 0

        try:
            async with async_playwright() as p:
                log_step += 1
                await _append_log(session, job_id, log_step, "Browser wird gestartet...")

                browser = await p.chromium.launch(headless=headless)

                # Recording setup: video + trace for debugging
                recording = should_record()
                rec_dir = get_recordings_dir("explore", str(job_id)) if recording else None
                context_kwargs = {
                    "viewport": {"width": 1280, "height": 900},
                    "locale": "de-DE",
                }
                if recording and rec_dir:
                    context_kwargs["record_video_dir"] = str(rec_dir / "videos")
                    context_kwargs["record_video_size"] = {"width": 1280, "height": 900}

                context = await browser.new_context(**context_kwargs)

                if recording and rec_dir:
                    await context.tracing.start(
                        screenshots=True, snapshots=True, sources=False
                    )
                    logger.info("Recording enabled for exploration job %s → %s", job_id, rec_dir)

                page = await context.new_page()
                page.set_default_timeout(timeout)

                log_step += 1
                await _append_log(session, job_id, log_step, f"Seite wird geladen: {source_url}")

                await page.goto(source_url, wait_until="networkidle")

                # ── Phase 1: Tree exploration (navigation + field extraction) ──
                log_step += 1
                await _append_log(session, job_id, log_step, "Formularstruktur wird erkundet...")

                tree = await explore_tree(page, source_url, timeout)

                total_common = len(tree.common_steps)
                total_branches = len(tree.branch_paths)

                log_step += 1
                if total_branches > 0:
                    await _append_log(
                        session, job_id, log_step,
                        f"{total_common} gemeinsame Schritte, {total_branches} Verzweigung(en) erkannt"
                    )
                else:
                    await _append_log(
                        session, job_id, log_step,
                        f"{total_common} Schritte erkannt (lineares Formular)"
                    )

                # ── Phase 2: LLM interpretation of each step ──
                log_step += 1
                await _append_log(session, job_id, log_step, "LLM interpretiert die Schritte...")

                # Renumber steps sequentially (auth gate + info pages may have left gaps)
                for i, step_exp in enumerate(tree.common_steps):
                    step_exp.step_num = i + 1
                for bp in tree.branch_paths:
                    offset = len(tree.common_steps)
                    for i, step_exp in enumerate(bp.step_explorations):
                        step_exp.step_num = offset + i + 1

                all_steps_to_interpret = list(tree.common_steps)
                for bp in tree.branch_paths:
                    all_steps_to_interpret.extend(bp.step_explorations)

                interpreted_steps = {}  # step_num -> step_data (keyed by step_num + path context)
                for step_exp in all_steps_to_interpret:
                    if not step_exp.raw_fields:
                        continue
                    # Skip if we already interpreted this exact step
                    cache_key = f"{step_exp.step_num}_{id(step_exp)}"

                    conditional_json = json.dumps(step_exp.conditional_logic, ensure_ascii=False, indent=2) if step_exp.conditional_logic else "None detected."
                    auth_info = "No auth gate detected."
                    if step_exp.auth_gate:
                        auth_info = f"BundID/eID gate detected. Bypassed via anonymous path."

                    # Merge conditional info into fields
                    fields_for_prompt = list(step_exp.raw_fields)
                    for f in fields_for_prompt:
                        label = f.get("label", "")
                        if label in step_exp.conditional_logic:
                            f["detected_conditional"] = step_exp.conditional_logic[label]

                    prompt = format_step_prompt(
                        fields_json=json.dumps(fields_for_prompt, ensure_ascii=False, indent=2),
                        page_title=step_exp.page_context.get("title", ""),
                        step_text=step_exp.page_context.get("stepText", ""),
                        headings=", ".join(step_exp.page_context.get("headings", [])),
                        conditional_logic_json=conditional_json,
                        auth_gate_info=auth_info,
                    )

                    try:
                        step_data = await llm.chat_json(
                            messages=[
                                {"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": prompt},
                            ],
                            images=[step_exp.screenshot] if step_exp.screenshot else None,
                        )
                    except Exception as e:
                        logger.error("LLM interpretation failed for step %d: %s", step_exp.step_num, e)
                        step_data = _fallback_step_data(step_exp.step_num, step_exp.raw_fields, step_exp.page_context)

                    step_data["step"] = step_exp.step_num
                    step_data.setdefault("navigation", {"next": None, "back": None})
                    interpreted_steps[cache_key] = step_data

                    log_step += 1
                    title = step_data.get("title", f"Schritt {step_exp.step_num}")
                    field_count = sum(len(s.get("fields", [])) for s in step_data.get("sections", []))
                    await _append_log(
                        session, job_id, log_step,
                        f"Schritt {step_exp.step_num}: {title} ({field_count} Felder)"
                    )

                # ── Phase 3: Detect outcome ──
                log_step += 1
                await _append_log(session, job_id, log_step, "Ergebnis wird erkannt...")

                # Prefer the final page screenshot (summary/confirmation page with action buttons)
                # Fall back to the last step's screenshot if we couldn't advance past it
                last_screenshot = tree.final_page_screenshot
                if not last_screenshot:
                    if tree.common_steps:
                        last_screenshot = tree.common_steps[-1].screenshot
                    elif tree.branch_paths and tree.branch_paths[0].step_explorations:
                        last_screenshot = tree.branch_paths[0].step_explorations[-1].screenshot

                try:
                    outcome = await llm.chat_json(
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": OUTCOME_DETECTION_PROMPT},
                        ],
                        images=[last_screenshot] if last_screenshot else None,
                    )
                except Exception:
                    outcome = {
                        "type": "print_and_sign",
                        "description": "Formular wird als PDF generiert.",
                        "submission_mode": "offline",
                    }

                # Deterministic button detection — use tree's final page buttons if available,
                # otherwise scan the current page
                if tree.final_page_buttons:
                    btn_texts = tree.final_page_buttons
                    import re as _re
                    outcome.setdefault("has_preview_button", any(_re.search(r'vorschau|preview', t, _re.I) for t in btn_texts))
                    outcome.setdefault("has_print_button", any(_re.search(r'drucken|print', t, _re.I) for t in btn_texts))
                    outcome.setdefault("preview_button_text", next((t for t in btn_texts if _re.search(r'vorschau|preview', t, _re.I)), None))
                    outcome.setdefault("print_button_text", next((t for t in btn_texts if _re.search(r'drucken|print', t, _re.I)), None))
                    # Override outcome type if we found print/preview buttons
                    if outcome.get("has_preview_button") or outcome.get("has_print_button"):
                        outcome["type"] = "print_and_sign"
                        outcome["submission_mode"] = "offline"
                else:
                    try:
                        button_info = await page.evaluate("""() => {
                            const btns = Array.from(document.querySelectorAll(
                                'button, a.btn, input[type="submit"], input[type="button"]'
                            ));
                            const texts = btns.map(b => (b.textContent || b.value || '').trim());
                            return {
                                has_preview: texts.some(t => /vorschau|preview/i.test(t)),
                                has_print: texts.some(t => /drucken|print/i.test(t)),
                                preview_text: texts.find(t => /vorschau|preview/i.test(t)) || null,
                                print_text: texts.find(t => /drucken|print/i.test(t)) || null,
                            };
                        }""")
                        outcome.setdefault("has_preview_button", button_info["has_preview"])
                        outcome.setdefault("has_print_button", button_info["has_print"])
                        outcome.setdefault("preview_button_text", button_info["preview_text"])
                        outcome.setdefault("print_button_text", button_info["print_text"])
                        if button_info["has_preview"] or button_info["has_print"]:
                            outcome["type"] = "print_and_sign"
                            outcome["submission_mode"] = "offline"
                    except Exception as e:
                        logger.debug("Deterministic button detection failed: %s", e)

                # Save trace before closing
                if recording and rec_dir:
                    trace_path = rec_dir / "trace.zip"
                    await context.tracing.stop(path=str(trace_path))
                    logger.info("Trace saved: %s", trace_path)
                    await context.close()  # Finalize video files
                else:
                    await context.close()
                await browser.close()

            # ── Phase 4: Compile graph ──
            # Build common steps list
            common_step_dicts = []
            for step_idx, step_exp in enumerate(tree.common_steps):
                cache_key = f"{step_exp.step_num}_{id(step_exp)}"
                if cache_key in interpreted_steps:
                    common_step_dicts.append(interpreted_steps[cache_key])
                elif step_exp.auth_gate and step_exp.auth_gate.detected:
                    # Auth gate step — fixed template
                    common_step_dicts.append({
                        "step": step_exp.step_num,
                        "id": "auth_gate",
                        "title": "Anmeldung (BundID / eID)",
                        "description": "Anmeldeoptionen: BundID, eID, Servicekonto. Bei der Automatisierung wird immer ohne Anmeldung fortgefahren.",
                        "step_type": "auth_gate",
                        "automation_action": "Weiter ohne Anmeldung",
                        "sections": [],
                        "navigation": {"next": None, "back": None},
                    })
                elif step_exp.page_context.get("title", "").lower().startswith("einwilligung"):
                    # Consent step — use fixed template
                    common_step_dicts.append({
                        "step": step_exp.step_num,
                        "id": "consent",
                        "title": "Einwilligungserklaerung",
                        "description": "Datenschutz- und Einwilligungserklaerung",
                        "sections": [{"section": "Datenschutzhinweis", "group_rule": None, "fields": [
                            {"label": "Datenschutzerklaerung", "type": "checkbox", "required": True}
                        ]}],
                        "navigation": {"next": None, "back": None},
                    })
                elif not step_exp.raw_fields and step_idx == len(tree.common_steps) - 1:
                    # Final page (last step, no fields) — will be enriched with outcome info below
                    common_step_dicts.append({
                        "step": step_exp.step_num,
                        "id": "final_page",
                        "title": "Ausfuellvorgang abschliessen",
                        "description": "Formular vollstaendig ausgefuellt.",
                        "step_type": "final_page",
                        "automation_action": "",  # Will be set after outcome detection
                        "available_actions": list(tree.final_page_buttons) if tree.final_page_buttons else [],
                        "sections": [],
                        "navigation": {"next": None, "back": None},
                    })
                elif not step_exp.raw_fields:
                    # Info/instruction page — no fields, just displayed
                    common_step_dicts.append({
                        "step": step_exp.step_num,
                        "id": "info_page",
                        "title": step_exp.page_context.get("title", "Hinweisseite"),
                        "description": "Informationsseite ohne Eingabefelder.",
                        "step_type": "info_page",
                        "automation_action": "Weiter wird geklickt",
                        "sections": [],
                        "navigation": {"next": None, "back": None},
                    })

            # Build branch paths
            branch_path_dicts = []
            for bp in tree.branch_paths:
                path_steps = []
                for step_exp in bp.step_explorations:
                    cache_key = f"{step_exp.step_num}_{id(step_exp)}"
                    if cache_key in interpreted_steps:
                        path_steps.append(interpreted_steps[cache_key])
                branch_path_dicts.append({
                    "path_id": bp.path_id,
                    "branch_point": bp.branch_point,
                    "branch_value": bp.branch_value,
                    "steps": path_steps,
                })

            # Enrich final_page step with outcome info
            for s in common_step_dicts:
                if s.get("step_type") == "final_page":
                    if outcome.get("type") == "print_and_sign":
                        s["description"] = "Formular vollstaendig ausgefuellt. PDF kann heruntergeladen, ausgedruckt und unterschrieben werden."
                        s["automation_action"] = (
                            "PDF wird generiert und an den Nutzer zurueckgegeben. "
                            "Der Nutzer muss das PDF ausdrucken, unterschreiben und per Post versenden."
                        )
                    elif outcome.get("type") == "digital_submission":
                        s["description"] = "Formular vollstaendig ausgefuellt. Digitale Einreichung moeglich."
                        s["automation_action"] = "Formular wird NICHT abgesendet. Der Nutzer muss die Einreichung selbst bestaetigen."
                    else:
                        s["description"] = outcome.get("description", "Formular vollstaendig ausgefuellt.")
                        s["automation_action"] = "Keine automatische Aktion. Der Nutzer muss den naechsten Schritt selbst durchfuehren."
                    break

            # Determine exploration type
            if branch_path_dicts:
                graph_data = {
                    "exploration_type": "branching",
                    "common_steps": common_step_dicts,
                    "branch_paths": branch_path_dicts,
                    "outcome": outcome,
                    # Also provide flat "steps" for backward compatibility
                    "steps": common_step_dicts + (branch_path_dicts[0]["steps"] if branch_path_dicts else []),
                }
            else:
                _fix_navigation(common_step_dicts)
                graph_data = {
                    "exploration_type": "linear",
                    "steps": common_step_dicts,
                    "outcome": outcome,
                }

            # ── Phase 4b: Validate and deduplicate mapped_keys ──
            _validate_and_deduplicate_mapped_keys(graph_data)

            # ── Phase 5: Generate MCP tool spec ──
            log_step += 1
            await _append_log(session, job_id, log_step, "MCP-Tool-Spezifikation wird generiert...")

            mcp_tool_spec = None
            try:
                form_title = "Unbekanntes Formular"
                all_steps = common_step_dicts
                if branch_path_dicts:
                    all_steps = common_step_dicts + branch_path_dicts[0].get("steps", [])
                for s in all_steps:
                    if s.get("id") != "consent":
                        form_title = s.get("title", form_title)
                        break

                spec_prompt = format_mcp_spec_prompt(
                    graph_json=json.dumps(graph_data, ensure_ascii=False, indent=2),
                    form_title=form_title,
                    source_url=source_url,
                )
                for attempt in range(2):
                    try:
                        mcp_tool_spec = await llm.chat_json(
                            messages=[
                                {"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": spec_prompt},
                            ],
                        )
                        break
                    except Exception as e:
                        if attempt == 0:
                            logger.warning("MCP spec generation attempt 1 failed: %s. Retrying...", e)
                        else:
                            raise
            except Exception as e:
                logger.error("MCP spec generation failed: %s", e)

            # ── Phase 6: Save to database ──
            log_step += 1
            await _append_log(session, job_id, log_step, "Formular-Graph wird gespeichert...")

            total_fields = sum(
                len(f.get("fields", []))
                for s in graph_data.get("steps", [])
                for f in s.get("sections", [])
            )

            async with async_session() as final_session:
                result = await final_session.execute(
                    select(ExplorationJob).where(ExplorationJob.id == job_id)
                )
                job = result.scalar_one()

                if form_graph_id:
                    fg_result = await final_session.execute(
                        select(FormGraph).where(FormGraph.id == form_graph_id)
                    )
                    form_graph = fg_result.scalar_one()
                    form_graph.graph_data = graph_data
                    form_graph.mcp_tool_spec = mcp_tool_spec
                    form_graph.status = FormStatus.REVIEW_PENDING
                    form_graph.explored_at = datetime.utcnow()
                    if tree.automation_notes.get("auth_gates"):
                        form_graph.automation_notes = tree.automation_notes

                    for s in all_steps:
                        if s.get("id") != "consent":
                            form_graph.title = s.get("title", form_graph.title)
                            break

                job.status = JobStatus.COMPLETED
                await final_session.commit()

            branch_info = f", {len(branch_path_dicts)} Pfad(e)" if branch_path_dicts else ""
            log_step += 1
            await _append_log(
                session, job_id, log_step,
                f"Erkundung abgeschlossen. {total_fields} Felder in {len(common_step_dicts)} Schritten{branch_info}."
            )

        except Exception as e:
            logger.exception("Exploration failed for job %s", job_id)
            async with async_session() as err_session:
                result = await err_session.execute(
                    select(ExplorationJob).where(ExplorationJob.id == job_id)
                )
                job = result.scalar_one()
                job.status = JobStatus.FAILED
                job.error = str(e)

                if form_graph_id:
                    fg_result = await err_session.execute(
                        select(FormGraph).where(FormGraph.id == form_graph_id)
                    )
                    fg = fg_result.scalar_one()
                    fg.status = FormStatus.EXPLORATION_FAILED

                await err_session.commit()


def _validate_and_deduplicate_mapped_keys(graph_data: dict):
    """Validate and deduplicate mapped_key values across the entire form graph.

    Safety net for LLM output — ensures all fields have unique mapped_keys.
    Runs after LLM interpretation, before saving to DB.
    """
    all_steps = graph_data.get("steps", [])
    # Also include branch path steps if present
    for bp in graph_data.get("branch_paths", []):
        all_steps = all_steps + bp.get("steps", [])

    # Collect all keys and their locations
    seen_keys: dict[str, list[tuple[dict, dict]]] = {}  # key -> [(field, section), ...]
    fields_without_key: list[tuple[dict, dict, dict]] = []  # (field, section, step)

    for step in all_steps:
        if step.get("id") == "consent":
            continue
        for section in step.get("sections", []):
            for field in section.get("fields", []):
                key = field.get("mapped_key")
                if not key:
                    fields_without_key.append((field, section, step))
                else:
                    seen_keys.setdefault(key, []).append((field, section))

    # Generate keys for fields missing them
    for field, section, step in fields_without_key:
        label = field.get("label", "unknown")
        key = _generate_deterministic_key(label, section.get("section", ""), step.get("id", ""))
        field["mapped_key"] = key
        seen_keys.setdefault(key, []).append((field, section))
        logger.warning("Generated missing mapped_key '%s' for field '%s'", key, label)

    # Deduplicate: if multiple fields share the same key, prefix with section name
    for key, entries in list(seen_keys.items()):
        if len(entries) <= 1:
            continue
        logger.warning("Duplicate mapped_key '%s' found on %d fields — deduplicating", key, len(entries))
        for i, (field, section) in enumerate(entries):
            section_name = section.get("section", "")
            if section_name:
                section_prefix = _slugify(section_name)
                new_key = f"{section_prefix}_{key}"
            else:
                new_key = f"{key}_{i + 1}"
            # Check if new key also collides
            suffix = 2
            final_key = new_key
            while final_key in seen_keys and final_key != key:
                final_key = f"{new_key}_{suffix}"
                suffix += 1
            field["mapped_key"] = final_key
            seen_keys.setdefault(final_key, [])


def _generate_deterministic_key(label: str, section_name: str, step_id: str) -> str:
    """Generate a deterministic mapped_key from label + context."""
    key = _slugify(label)
    if section_name:
        section_slug = _slugify(section_name)
        return f"{section_slug}_{key}"
    if step_id and step_id != "consent":
        return f"{step_id}_{key}"
    return key


def _slugify(text: str) -> str:
    """Convert German text to a snake_case slug."""
    slug = text.lower().strip()
    for old, new in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        slug = slug.replace(old, new)
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")[:40]


def _fix_navigation(steps: list[dict]):
    """Set next/back navigation links between steps."""
    for i, step in enumerate(steps):
        step_id = step.get("id", f"step_{step.get('step', i + 1)}")
        step["id"] = step_id

        prev_id = steps[i - 1].get("id") if i > 0 else None
        next_id = steps[i + 1].get("id") if i < len(steps) - 1 else None

        step["navigation"] = {
            "next": next_id,
            "back": prev_id,
        }


def _fallback_step_data(step_num: int, raw_fields: list[dict], page_context: dict) -> dict:
    """Create a basic step structure from raw data when LLM fails."""
    fields = []
    for f in raw_fields:
        field = {
            "label": f.get("label", "Unbekanntes Feld"),
            "type": _normalize_field_type(f.get("type", "text")),
            "required": f.get("required", False),
        }
        if f.get("options"):
            field["options"] = f["options"]
        if f.get("help"):
            field["help"] = f["help"]
        fields.append(field)

    return {
        "title": page_context.get("title", f"Schritt {step_num}"),
        "id": f"step_{step_num}",
        "description": "",
        "sections": [{
            "section": "Formularfelder",
            "group_rule": None,
            "fields": fields,
        }],
    }


def _normalize_field_type(raw_type: str) -> str:
    """Normalize HTML input type to our schema types."""
    mapping = {
        "text": "text",
        "email": "email",
        "tel": "text",
        "number": "text",
        "date": "date",
        "select": "select",
        "select-one": "select",
        "radio": "radio",
        "checkbox": "checkbox",
        "textarea": "textarea",
    }
    return mapping.get(raw_type, "text")


# ═══════════════════════════════════════════════════════════════════════════
#  MOCK EXPLORER (for tests and demos)
# ═══════════════════════════════════════════════════════════════════════════

MOCK_STEPS = [
    {"step": 1, "message": "Seite wird geladen..."},
    {"step": 2, "message": "Formularstruktur wird analysiert..."},
    {"step": 3, "message": "Schritt 1 erkannt: Einwilligungserklaerung"},
    {"step": 4, "message": "1 Feld gefunden (Checkbox)"},
    {"step": 5, "message": "Navigation zu Schritt 2..."},
    {"step": 6, "message": "Schritt 2 erkannt: Vollmachtgebende Person"},
    {"step": 7, "message": "9 Felder gefunden (Text, Select, Date, Email)"},
    {"step": 8, "message": "Pflichtgruppe erkannt: Kontakt (mindestens eins)"},
    {"step": 9, "message": "Navigation zu Schritt 3..."},
    {"step": 10, "message": "Schritt 3 erkannt: Bevollmaechtigte Person"},
    {"step": 11, "message": "6 Felder gefunden (Text, Select, Date)"},
    {"step": 12, "message": "Navigation zu Schritt 4..."},
    {"step": 13, "message": "Schritt 4 erkannt: Bevollmaechtigung"},
    {"step": 14, "message": "1 Feld gefunden (Select)"},
    {"step": 15, "message": "Ergebnis: Ausdrucken & Unterschreiben (PDF)"},
    {"step": 16, "message": "MCP-Tool-Spezifikation wird generiert..."},
    {"step": 17, "message": "Erkundung abgeschlossen. 17 Felder in 4 Schritten."},
]


async def run_mock_exploration(job_id: UUID):
    """Simulate form exploration with delays. Loads Vollmacht reference data as result."""
    async with async_session() as session:
        result = await session.execute(
            select(ExplorationJob).where(ExplorationJob.id == job_id)
        )
        job = result.scalar_one()
        job.status = JobStatus.RUNNING
        job.progress_log = []
        await session.commit()

        try:
            for entry in MOCK_STEPS:
                await asyncio.sleep(1.2)
                await _append_log(session, job_id, entry["step"], entry["message"])

            ref_path = Path(__file__).parent.parent / "reference-data" / "form-graph-vollmacht-ausweis.json"
            graph_data = json.loads(ref_path.read_text())

            # Use a fresh session for the final update to avoid stale state
            # from the _append_log commits
            async with async_session() as final_session:
                result = await final_session.execute(
                    select(ExplorationJob).where(ExplorationJob.id == job_id)
                )
                job = result.scalar_one()

                if job.form_graph_id:
                    fg_result = await final_session.execute(
                        select(FormGraph).where(FormGraph.id == job.form_graph_id)
                    )
                    form_graph = fg_result.scalar_one()
                    form_graph.graph_data = graph_data
                    form_graph.status = FormStatus.REVIEW_PENDING
                    form_graph.explored_at = datetime.utcnow()

                job.status = JobStatus.COMPLETED
                await final_session.commit()

        except Exception as e:
            logger.exception("Mock exploration failed")
            async with async_session() as err_session:
                result = await err_session.execute(
                    select(ExplorationJob).where(ExplorationJob.id == job_id)
                )
                job = result.scalar_one()
                job.status = JobStatus.FAILED
                job.error = str(e)
                await err_session.commit()


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT — dispatches to real or mock based on config
# ═══════════════════════════════════════════════════════════════════════════

async def run_exploration(job_id: UUID, llm_config: LLMConfig | None = None):
    """Run exploration, dispatching to real or mock based on EXPLORER_MODE env var."""
    mode = os.environ.get("EXPLORER_MODE", "real").lower()

    if mode == "mock" or llm_config is None or not llm_config.api_key:
        logger.info("Running mock exploration for job %s", job_id)
        await run_mock_exploration(job_id)
    else:
        logger.info("Running real exploration for job %s", job_id)
        await run_real_exploration(job_id, llm_config)
