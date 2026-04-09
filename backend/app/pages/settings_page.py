from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.inertia_setup import InertiaDep
from backend.app.services.llm_client import LLMClient, LLMProvider, PROVIDER_DEFAULT_MODELS
from backend.app.services.settings_service import (
    get_all_settings,
    set_setting,
    get_llm_config,
    SECRET_KEYS,
)

router = APIRouter()


def _mask_key(key: str) -> str:
    """Mask an API key for display: show first 8 and last 4 chars."""
    if len(key) <= 12:
        return "*" * len(key) if key else ""
    return key[:8] + "*" * (len(key) - 12) + key[-4:]


@router.get("/settings")
async def settings_page(inertia: InertiaDep, db: AsyncSession = Depends(get_db)):
    settings = await get_all_settings(db)
    # Mask the API key for the frontend
    display_settings = dict(settings)
    display_settings["llm_api_key"] = _mask_key(settings.get("llm_api_key", ""))
    display_settings["has_api_key"] = bool(settings.get("llm_api_key", ""))

    return await inertia.render("Settings", props={
        "settings": display_settings,
        "providers": [
            {"value": p.value, "label": p.value.capitalize(), "defaultModel": PROVIDER_DEFAULT_MODELS.get(p.value, "")}
            for p in LLMProvider
        ],
    })


class SettingsUpdateRequest(BaseModel):
    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_temperature: str | None = None


@router.post("/settings")
async def update_settings(
    body: SettingsUpdateRequest,
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
):
    updates = body.model_dump(exclude_none=True)

    # Don't save the masked placeholder back
    if "llm_api_key" in updates:
        if "*" in updates["llm_api_key"]:
            del updates["llm_api_key"]

    for key, value in updates.items():
        await set_setting(db, key, str(value))

    # Re-render the settings page with flash
    settings = await get_all_settings(db)
    display_settings = dict(settings)
    display_settings["llm_api_key"] = _mask_key(settings.get("llm_api_key", ""))
    display_settings["has_api_key"] = bool(settings.get("llm_api_key", ""))

    return await inertia.render("Settings", props={
        "settings": display_settings,
        "providers": [
            {"value": p.value, "label": p.value.capitalize(), "defaultModel": PROVIDER_DEFAULT_MODELS.get(p.value, "")}
            for p in LLMProvider
        ],
        "flash": {"success": "Einstellungen gespeichert."},
    })
