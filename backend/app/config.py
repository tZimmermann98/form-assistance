from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://agentic:agentic_dev@localhost:5432/agentic_ms"
    environment: Literal["development", "production"] = "development"
    vite_dev_url: str = "http://localhost:5173"

    # Explorer settings
    explorer_mode: Literal["real", "mock"] = "real"
    explorer_headless: bool = True
    explorer_timeout: int = 30000  # Page navigation timeout in ms

    # MCP server
    mcp_server_port: int = 8001

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
