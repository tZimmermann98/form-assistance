import pytest
from httpx import AsyncClient

from backend.app.models.settings import PlatformSettings


@pytest.mark.asyncio
async def test_settings_page_returns_200(client: AsyncClient):
    response = await client.get("/settings")
    assert response.status_code == 200
    assert '"Settings"' in response.text


@pytest.mark.asyncio
async def test_settings_page_contains_providers(client: AsyncClient):
    response = await client.get("/settings")
    assert "anthropic" in response.text
    assert "openai" in response.text


@pytest.mark.asyncio
async def test_save_settings(client: AsyncClient, db_session):
    response = await client.post(
        "/settings",
        json={
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "llm_temperature": "0.5",
        },
    )
    # Inertia POST re-renders the page
    assert response.status_code == 200

    from sqlalchemy import select
    result = await db_session.execute(
        select(PlatformSettings).where(PlatformSettings.key == "llm_provider")
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.value == "openai"


@pytest.mark.asyncio
async def test_api_key_is_masked(client: AsyncClient, db_session):
    # Save an API key
    row = PlatformSettings(key="llm_api_key", value="sk-test-1234567890abcdef", is_secret=False)
    db_session.add(row)
    await db_session.commit()

    response = await client.get("/settings")
    assert response.status_code == 200
    # The full key should NOT appear in the response
    assert "sk-test-1234567890abcdef" not in response.text
    # But we should see the masked version
    assert "sk-test-" in response.text
    assert "cdef" in response.text


@pytest.mark.asyncio
async def test_test_llm_endpoint_no_key(client: AsyncClient):
    response = await client.post("/api/v1/settings/test-llm")
    data = response.json()
    assert data["success"] is False
    assert "Schluessel" in data["error"]
