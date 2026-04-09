"""Chat API for the test chat interface.

Implements a basic agent loop: user message → LLM (with tool definitions) → tool call or text response.
"""

import base64
import json
import logging
import uuid as _uuid
from time import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.services.llm_client import LLMClient, LLMProvider
from backend.app.services.settings_service import get_llm_config, get_all_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# ── In-memory PDF cache with TTL ──────────────────────────────────────────
_pdf_cache: dict[str, tuple[bytes, float]] = {}  # token -> (pdf_bytes, expiry_ts)
_PDF_TTL = 900  # 15 minutes


def _store_pdf(pdf_bytes: bytes) -> str:
    """Store PDF bytes and return a download token."""
    now = time()
    # Clean expired entries
    expired = [k for k, (_, exp) in _pdf_cache.items() if exp < now]
    for k in expired:
        del _pdf_cache[k]
    token = str(_uuid.uuid4())
    _pdf_cache[token] = (pdf_bytes, now + _PDF_TTL)
    return token

SYSTEM_PROMPT = (
    "Du bist ein Assistent der Stadt Muenster. Du hilfst Buergern dabei, "
    "Formulare auszufuellen. Frage alle benoetigten Informationen ab und "
    "nutze die verfuegbaren Tools, um das Formular automatisch auszufuellen.\n\n"
    "Wenn ein Buerger ein Formular ausfuellen moechte:\n"
    "1. Nutze list_form_tools() um verfuegbare Formulare anzuzeigen\n"
    "2. Frage alle benoetigten Felder einzeln oder gebuendelt ab\n"
    "3. Nutze fill_form() mit den gesammelten Daten\n"
    "4. Teile dem Buerger das Ergebnis mit\n\n"
    "Antworte immer auf Deutsch."
)


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
    attachments: list[dict[str, str]] | None = None  # [{name, base64}]


class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    attachments: list[dict[str, str]] | None = None  # [{name, base64}]


async def _get_mcp_tools(db: AsyncSession) -> list[dict]:
    """Fetch available tools from the database directly."""
    from sqlalchemy import select as sa_select
    from backend.app.models.form_graph import FormGraph, FormStatus
    from mcp_server.tool_generator import generate_tool_definition

    tools = []

    # Query approved forms
    result = await db.execute(
        sa_select(FormGraph).where(
            FormGraph.status.in_([FormStatus.APPROVED, FormStatus.DEGRADED])
        )
    )
    forms = result.scalars().all()

    for form in forms:
        tool_def = generate_tool_definition(form)
        if tool_def:
            tools.append({
                "name": tool_def["name"],  # Already has fill_form__ prefix
                "description": tool_def.get("description", f"Formular ausfuellen: {tool_def['name']}"),
                "input_schema": tool_def.get("input_schema", {"type": "object", "properties": {}}),
                "_form_id": str(form.id),
                "_graph_data": form.graph_data,
                "_source_url": form.source_url,
            })

    return tools


@router.post("/chat")
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Process a chat message through the LLM with tool definitions."""
    config = await get_llm_config(db)
    if not config.api_key:
        raise HTTPException(status_code=400, detail="Kein LLM API-Schluessel konfiguriert. Bitte unter Einstellungen hinterlegen.")

    client = LLMClient(config)
    tools = await _get_mcp_tools(db)

    # Build messages with system prompt
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(body.messages)

    # Call LLM — branch based on provider
    if config.provider == LLMProvider.ANTHROPIC:
        return await _chat_anthropic(client, messages, tools)
    else:
        return await _chat_openai(client, messages, tools)


async def _chat_anthropic(client: LLMClient, messages: list[dict], tools: list[dict]) -> dict:
    """Call Anthropic API with tool use support."""
    import anthropic

    anthropic_client = client._get_anthropic_client()

    # Separate system from conversation
    system_text = ""
    conversation = []
    for msg in messages:
        if msg["role"] == "system":
            system_text += msg["content"] + "\n"
        else:
            conversation.append(msg)

    # Convert tools to Anthropic format
    anthropic_tools = []
    for tool in tools:
        anthropic_tools.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": tool.get("input_schema", {"type": "object", "properties": {}}),
        })

    try:
        response = await anthropic_client.messages.create(
            model=client.config.effective_model(),
            max_tokens=4096,
            system=system_text.strip(),
            messages=conversation,
            tools=anthropic_tools if anthropic_tools else anthropic.NOT_GIVEN,
            temperature=client.config.temperature,
        )

        # Parse response
        result_blocks = []
        for block in response.content:
            if block.type == "text":
                result_blocks.append({"type": "text", "content": block.text})
            elif block.type == "tool_use":
                result_blocks.append({
                    "type": "tool_call",
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input,
                })

        return {"blocks": result_blocks, "stop_reason": response.stop_reason}

    except Exception as e:
        logger.error("Anthropic chat failed: %s", e)
        return {"blocks": [{"type": "text", "content": f"Fehler: {str(e)}"}], "stop_reason": "error"}


async def _chat_openai(client: LLMClient, messages: list[dict], tools: list[dict]) -> dict:
    """Call OpenAI-compatible API with tool use support."""
    openai_client = client._get_openai_client()

    # Convert tools to OpenAI format
    openai_tools = []
    for tool in tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        })

    try:
        kwargs = {
            "model": client.config.effective_model(),
            "messages": messages,
            "temperature": client.config.temperature,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        # Newer OpenAI models require max_completion_tokens instead of max_tokens.
        # Detect which to use and cache via the client instance.
        if getattr(client, "_use_legacy_max_tokens", False):
            kwargs["max_tokens"] = 4096
            response = await openai_client.chat.completions.create(**kwargs)
        else:
            try:
                response = await openai_client.chat.completions.create(
                    **kwargs, max_completion_tokens=4096,
                )
            except Exception as e:
                if "max_tokens" in str(e) or "unsupported_parameter" in str(e):
                    client._use_legacy_max_tokens = True
                    kwargs["max_tokens"] = 4096
                    response = await openai_client.chat.completions.create(**kwargs)
                else:
                    raise
        choice = response.choices[0]

        result_blocks = []
        if choice.message.content:
            result_blocks.append({"type": "text", "content": choice.message.content})

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                result_blocks.append({
                    "type": "tool_call",
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments,
                })

        return {"blocks": result_blocks, "stop_reason": choice.finish_reason}

    except Exception as e:
        logger.error("OpenAI chat failed: %s", e)
        return {"blocks": [{"type": "text", "content": f"Fehler: {str(e)}"}], "stop_reason": "error"}


@router.post("/chat/execute-tool")
async def execute_tool(body: ToolCallRequest, db: AsyncSession = Depends(get_db)):
    """Execute a tool call — runs the executor directly, no MCP server dependency."""
    from sqlalchemy import select as sa_select
    from backend.app.models.form_graph import FormGraph, FormStatus
    from mcp_server.tool_generator import generate_tool_definition

    try:
        tool_name = body.tool_name
        args = body.arguments

        if tool_name == "list_form_tools":
            # List approved forms as tools
            result_db = await db.execute(
                sa_select(FormGraph).where(
                    FormGraph.status.in_([FormStatus.APPROVED, FormStatus.DEGRADED])
                )
            )
            forms = result_db.scalars().all()
            lines = []
            for form in forms:
                td = generate_tool_definition(form)
                if td:
                    props = td.get("input_schema", {}).get("properties", {})
                    lines.append(f"- {td['name']}: {td.get('description', '')} ({len(props)} Felder)")
            return {"result": "\n".join(lines) if lines else "Keine freigegebenen Formulare verfuegbar."}

        elif tool_name.startswith("fill_form__"):
            # Execute form fill directly via the executor
            # Strip only the first fill_form__ prefix to get the tool_name from mcp_tool_spec
            actual_name = tool_name[len("fill_form__"):]

            # Find the form
            result_db = await db.execute(
                sa_select(FormGraph).where(
                    FormGraph.status.in_([FormStatus.APPROVED, FormStatus.DEGRADED])
                )
            )
            forms = result_db.scalars().all()

            target_form = None
            for form in forms:
                td = generate_tool_definition(form)
                if td:
                    # Match against tool_name from spec (without prefix)
                    spec_name = (form.mcp_tool_spec or {}).get("tool_name", "")
                    if actual_name == spec_name or td["name"] == tool_name:
                        target_form = form
                        break

            if not target_form:
                return {"result": f"Formular '{actual_name}' nicht gefunden."}

            # Inject file attachments into field_values for file-type fields
            field_values = dict(args)
            if body.attachments:
                # Find file-type fields in the form graph and match by index
                file_fields = []
                for step in target_form.graph_data.get("steps", []):
                    for section in step.get("sections", []):
                        for field in section.get("fields", []):
                            if field.get("type") == "file" and field.get("mapped_key"):
                                file_fields.append(field["mapped_key"])
                # Map attachments to file fields by order
                for i, att in enumerate(body.attachments):
                    if i < len(file_fields):
                        field_values[file_fields[i]] = att["base64"]

            from executor.runner import FormExecutor
            executor = FormExecutor()
            result = await executor.execute(
                form_graph=target_form.graph_data,
                field_values=field_values,
                source_url=target_form.source_url,
            )

            if result["status"] == "success":
                response = {
                    "result": "Formular erfolgreich ausgefuellt.",
                    "screenshot": result.get("screenshot_base64"),
                    "outcome_type": result.get("outcome_type"),
                }
                if result.get("pdf_base64"):
                    pdf_bytes = base64.b64decode(result["pdf_base64"])
                    token = _store_pdf(pdf_bytes)
                    response["pdf_url"] = f"/api/v1/chat/download/{token}"
                    response["result"] += " PDF zum Herunterladen bereit."
                else:
                    response["result"] += " NICHT abgesendet — Buerger muss pruefen und absenden."
                return response
            elif result["status"] == "validation_error":
                return {"result": f"Validierungsfehler: {result.get('error', '')}"}
            elif result["status"] == "field_not_found":
                return {"result": f"Feld nicht gefunden: {result.get('error', '')}. Formular wird ueberprueft."}
            else:
                return {"result": f"Fehler: {result.get('error', result.get('errors', 'Unbekannt'))}"}

        else:
            return {"result": f"Unbekanntes Tool: {tool_name}"}

    except Exception as e:
        logger.error("Tool execution failed: %s", e)
        return {"result": f"Tool-Ausfuehrung fehlgeschlagen: {str(e)}"}


@router.get("/chat/download/{token}")
async def download_pdf(token: str):
    """Download a temporarily stored PDF (expires after 15 minutes)."""
    entry = _pdf_cache.get(token)
    if not entry or entry[1] < time():
        if token in _pdf_cache:
            del _pdf_cache[token]
        raise HTTPException(status_code=404, detail="PDF abgelaufen oder nicht gefunden.")
    return Response(
        content=entry[0],
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=formular.pdf"},
    )
