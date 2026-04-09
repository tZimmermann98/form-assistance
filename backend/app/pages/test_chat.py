from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.inertia_setup import InertiaDep
from backend.app.models.form_graph import FormGraph, FormStatus
from backend.app.services.settings_service import get_all_settings
from mcp_server.tool_generator import generate_tool_definition

router = APIRouter()


@router.get("/test-chat")
async def test_chat_page(inertia: InertiaDep, db: AsyncSession = Depends(get_db)):
    settings = await get_all_settings(db)
    has_api_key = bool(settings.get("llm_api_key", ""))
    provider = settings.get("llm_provider", "anthropic")
    model = settings.get("llm_model", "")

    # Get available tools directly from DB (not via MCP server module)
    tools = []
    result = await db.execute(
        select(FormGraph).where(
            FormGraph.status.in_([FormStatus.APPROVED, FormStatus.DEGRADED])
        )
    )
    forms = result.scalars().all()
    for form in forms:
        tool_def = generate_tool_definition(form)
        if tool_def:
            tools.append({
                "name": tool_def["name"],
                "description": tool_def.get("description", ""),
                "fieldCount": len(tool_def.get("input_schema", {}).get("properties", {})),
            })

    return await inertia.render("TestChat", props={
        "hasApiKey": has_api_key,
        "provider": provider,
        "model": model,
        "availableTools": tools,
    })
