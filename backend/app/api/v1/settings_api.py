from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.services.llm_client import LLMClient
from backend.app.services.settings_service import get_llm_config

router = APIRouter()


@router.post("/settings/test-llm")
async def test_llm_connection(db: AsyncSession = Depends(get_db)):
    """Test the LLM connection with current settings."""
    config = await get_llm_config(db)

    if not config.api_key:
        return {"success": False, "error": "Kein API-Schluessel konfiguriert."}

    client = LLMClient(config)
    result = await client.test_connection()
    return result
