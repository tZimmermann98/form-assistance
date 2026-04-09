"""MCP server with dynamic tool registration from approved FormGraphs.

Transport: Streamable HTTP (current MCP standard for remote servers).
On startup, loads all approved forms. Refreshes on demand.
"""

import asyncio
import logging
import os

from mcp.server.fastmcp import FastMCP

from mcp_server.tool_generator import generate_tool_definition

logger = logging.getLogger(__name__)

# The MCP server instance
_port = int(os.environ.get("MCP_SERVER_PORT", "8001"))
mcp = FastMCP(
    "Agentic Muenster",
    instructions=(
        "MCP server for German municipal web forms. "
        "Each tool corresponds to an approved form that can be filled out automatically. "
        "Citizen data is processed on-premise only and discarded after execution."
    ),
    host="0.0.0.0",
    port=_port,
)

# Cache of tool definitions: tool_name → {definition, form_id, graph_data, source_url, status}
_tools_cache: dict[str, dict] = {}


async def _get_db_session():
    """Get a database session. Imports here to avoid circular deps."""
    from backend.app.database import async_session
    async with async_session() as session:
        yield session


async def _fetch_approved_forms():
    """Fetch all approved/degraded forms from the database."""
    from sqlalchemy import select
    from backend.app.database import async_session
    from backend.app.models.form_graph import FormGraph, FormStatus

    async with async_session() as session:
        result = await session.execute(
            select(FormGraph).where(
                FormGraph.status.in_([
                    FormStatus.APPROVED,
                    FormStatus.DEGRADED,
                    FormStatus.OUTDATED,
                ])
            )
        )
        return result.scalars().all()


async def refresh_tools():
    """Reload approved forms from DB and rebuild the tool cache."""
    global _tools_cache
    forms = await _fetch_approved_forms()
    new_cache = {}

    for form in forms:
        tool_def = generate_tool_definition(form)
        if tool_def:
            new_cache[tool_def["name"]] = {
                "definition": tool_def,
                "form_id": str(form.id),
                "graph_data": form.graph_data,
                "source_url": form.source_url,
                "status": form.status,
            }

    _tools_cache = new_cache
    logger.info("Refreshed MCP tools: %d active", len(_tools_cache))
    return len(_tools_cache)


async def _trigger_re_exploration(form_id: str):
    """Trigger re-exploration for a form after execution failure."""
    from sqlalchemy import select
    from backend.app.database import async_session
    from backend.app.models.form_graph import FormGraph, FormStatus
    from backend.app.models.exploration_job import ExplorationJob, JobStatus
    from explorer.agent import run_exploration

    try:
        async with async_session() as session:
            result = await session.execute(
                select(FormGraph).where(FormGraph.id == form_id)
            )
            form = result.scalar_one_or_none()
            if not form:
                return

            # Set status to degraded
            form.status = FormStatus.DEGRADED
            await session.flush()

            # Create re-exploration job
            job = ExplorationJob(
                form_graph_id=form.id,
                source_url=form.source_url,
                status=JobStatus.PENDING,
                progress_log=[],
            )
            session.add(job)
            await session.commit()

            # Load LLM config and start exploration
            from backend.app.services.settings_service import get_llm_config
            llm_config = await get_llm_config(session)
            asyncio.create_task(run_exploration(job.id, llm_config))

            logger.info("Triggered re-exploration for form %s (job %s)", form_id, job.id)

    except Exception as e:
        logger.error("Failed to trigger re-exploration for %s: %s", form_id, e)


# ── Register dynamic tools ──────────────────────────────────────────────

# We use a single tool handler that dispatches based on tool name.
# FastMCP's @mcp.tool() decorator registers static tools, but we need dynamic ones.
# So we register a refresh tool and handle form tools via the lower-level API.

@mcp.tool()
async def refresh_form_tools() -> str:
    """Reload all approved forms from the database. Call this after approving a new form."""
    count = await refresh_tools()
    return f"Refreshed. {count} form tools available."


@mcp.tool()
async def list_form_tools() -> str:
    """List all available form-filling tools with their descriptions and required parameters."""
    if not _tools_cache:
        await refresh_tools()

    if not _tools_cache:
        return "No approved forms available. Ask a city worker to explore and approve a form first."

    lines = []
    for name, tool in _tools_cache.items():
        defn = tool["definition"]
        status = tool.get("status", "approved")
        schema = defn.get("input_schema", {})
        required = schema.get("required", [])
        props = schema.get("properties", {})

        lines.append(f"## {name}")
        lines.append(f"Status: {status}")
        lines.append(f"Description: {defn.get('description', 'N/A')}")
        lines.append(f"Required fields ({len(required)}):")
        for key in required:
            prop = props.get(key, {})
            desc = prop.get("description", key)
            enum = prop.get("enum")
            if enum:
                lines.append(f"  - {key}: {desc} (options: {', '.join(enum)})")
            else:
                lines.append(f"  - {key}: {desc}")

        optional = [k for k in props if k not in required]
        if optional:
            lines.append(f"Optional fields ({len(optional)}):")
            for key in optional:
                prop = props.get(key, {})
                lines.append(f"  - {key}: {prop.get('description', key)}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def fill_form(tool_name: str, field_values: dict) -> str:
    """Fill a municipal form with the provided field values.

    Args:
        tool_name: The name of the form tool (from list_form_tools)
        field_values: Dictionary of field keys → values
    """
    if not _tools_cache:
        await refresh_tools()

    tool = _tools_cache.get(tool_name)
    if not tool:
        available = ", ".join(_tools_cache.keys()) if _tools_cache else "none"
        return f"Unknown form tool: '{tool_name}'. Available tools: {available}"

    status = tool.get("status", "approved")

    # Status gating
    if status == "broken":
        return (
            "This form service is temporarily unavailable. "
            "The form has changed and is being re-verified by the city. "
            "Please try again later."
        )

    warnings = []
    if status == "degraded":
        warnings.append(
            "Warning: This form was recently flagged for changes. "
            "Execution will proceed but some fields may not work correctly."
        )
    if status == "outdated":
        warnings.append(
            "Warning: This form has been updated since last approval. "
            "Some new fields may be missing from the tool definition."
        )

    # Execute the form
    from executor.runner import FormExecutor

    executor = FormExecutor()
    result = await executor.execute(
        form_graph=tool["graph_data"],
        field_values=field_values,
        source_url=tool["source_url"],
    )

    # Handle field_not_found → trigger re-exploration
    if result.get("status") == "field_not_found" and result.get("trigger_recheck"):
        await _trigger_re_exploration(tool["form_id"])
        return (
            f"Form execution failed: {result.get('error', 'unknown')}. "
            "The city has been notified to check for form changes. "
            "Please try again later."
        )

    # Build response
    response_parts = []
    if warnings:
        response_parts.extend(warnings)

    if result["status"] == "success":
        response_parts.append(
            "Form filled successfully. All fields have been entered. "
            "IMPORTANT: The form has NOT been submitted — a human must review and click submit."
        )
    elif result["status"] == "partial":
        response_parts.append(
            "Form partially filled. Some fields had errors:\n"
            + "\n".join(f"- {e}" for e in result.get("errors", []))
        )
    else:
        response_parts.append(f"Form execution error: {result.get('error', 'unknown')}")

    # Include audit summary (no PII)
    audit = result.get("audit_log", [])
    fill_count = sum(1 for a in audit if a.get("action") == "fill_field")
    response_parts.append(f"\nAudit: {fill_count} fields filled across {len([s for s in tool['graph_data'].get('steps', [])])} steps.")

    # If PDF was captured, return it as an embedded resource
    if result.get("pdf_base64"):
        response_parts.append(
            "\nPDF wurde generiert. Der Buerger muss das PDF ausdrucken, "
            "unterschreiben und per Post an die Behoerde senden."
        )
        return [
            {"type": "text", "text": "\n\n".join(response_parts)},
            {"type": "resource", "resource": {
                "uri": f"data:application/pdf;base64,{result['pdf_base64']}",
                "mimeType": "application/pdf",
                "text": result["pdf_base64"],
            }},
        ]

    return "\n\n".join(response_parts)


# ── Server startup ───────────────────────────────────────────────────────

def run_server():
    """Run the MCP server with Streamable HTTP transport."""
    logger.info("Starting MCP server on port %d", _port)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_server()
