from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.inertia_setup import InertiaDep

router = APIRouter()


@router.get("/connect")
async def connect_guide_page(
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
):
    # Detect the server hostname from the request
    host = request.headers.get("host", "localhost:8000")
    hostname = host.split(":")[0]
    mcp_url = f"http://{hostname}:8001/mcp"

    # Get available tools
    tools = []
    try:
        from mcp_server.server import _tools_cache, refresh_tools
        if not _tools_cache:
            await refresh_tools()
        for name, tool in _tools_cache.items():
            defn = tool["definition"]
            tools.append({
                "name": name,
                "description": defn.get("description", ""),
                "fieldCount": len(defn.get("input_schema", {}).get("properties", {})),
                "status": tool.get("status", "approved"),
            })
    except Exception:
        pass

    return await inertia.render("ConnectGuide", props={
        "mcpUrl": mcp_url,
        "hostname": hostname,
        "tools": tools,
    })
