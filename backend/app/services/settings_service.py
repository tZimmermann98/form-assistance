"""Service for reading/writing platform settings with optional encryption."""

import os
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.settings import PlatformSettings

logger = logging.getLogger(__name__)

# Fernet key from environment — generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
_FERNET_KEY = os.environ.get("SETTINGS_ENCRYPTION_KEY", "")
_fernet = None


def _get_fernet() -> Fernet | None:
    global _fernet
    if _fernet is not None:
        return _fernet
    if _FERNET_KEY:
        try:
            _fernet = Fernet(_FERNET_KEY.encode())
            return _fernet
        except Exception:
            logger.warning("Invalid SETTINGS_ENCRYPTION_KEY, secrets will be stored in plain text")
    return None


def _encrypt(value: str) -> str:
    f = _get_fernet()
    if f:
        return f.encrypt(value.encode()).decode()
    return value


def _decrypt(value: str) -> str:
    f = _get_fernet()
    if f:
        try:
            return f.decrypt(value.encode()).decode()
        except InvalidToken:
            # Value might not be encrypted (e.g. migrated from plain text)
            return value
    return value


# Default settings
DEFAULTS = {
    "llm_provider": "anthropic",
    "llm_base_url": "",
    "llm_api_key": "",
    "llm_model": "claude-sonnet-4-20250514",
    "llm_temperature": "0.0",
}

SECRET_KEYS = {"llm_api_key"}


async def get_setting(db: AsyncSession, key: str) -> str:
    """Get a setting value by key, returns default if not set."""
    result = await db.execute(
        select(PlatformSettings).where(PlatformSettings.key == key)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return DEFAULTS.get(key, "")
    value = row.value
    if row.is_secret:
        value = _decrypt(value)
    return value


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    """Set a setting value. Encrypts if it's a secret key."""
    is_secret = key in SECRET_KEYS
    stored_value = _encrypt(value) if is_secret else value

    result = await db.execute(
        select(PlatformSettings).where(PlatformSettings.key == key)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = PlatformSettings(key=key, value=stored_value, is_secret=is_secret)
        db.add(row)
    else:
        row.value = stored_value
        row.is_secret = is_secret
    await db.commit()


async def get_all_settings(db: AsyncSession) -> dict[str, str]:
    """Get all settings as a dict. Secret values are decrypted."""
    result = await db.execute(select(PlatformSettings))
    rows = result.scalars().all()
    settings = dict(DEFAULTS)  # start with defaults
    for row in rows:
        value = _decrypt(row.value) if row.is_secret else row.value
        settings[row.key] = value
    return settings


async def get_llm_config(db: AsyncSession):
    """Build an LLMConfig from current settings."""
    from backend.app.services.llm_client import LLMConfig
    s = await get_all_settings(db)
    return LLMConfig(
        provider=s.get("llm_provider", "anthropic"),
        api_key=s.get("llm_api_key", ""),
        model=s.get("llm_model", ""),
        base_url=s.get("llm_base_url", ""),
        temperature=float(s.get("llm_temperature", "0.0")),
    )
