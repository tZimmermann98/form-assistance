import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_test_chat_page_returns_200(client: AsyncClient):
    response = await client.get("/test-chat")
    assert response.status_code == 200
    assert '"TestChat"' in response.text


@pytest.mark.asyncio
async def test_connect_guide_returns_200(client: AsyncClient):
    response = await client.get("/connect")
    assert response.status_code == 200
    assert '"ConnectGuide"' in response.text


@pytest.mark.asyncio
async def test_connect_guide_contains_mcp_url(client: AsyncClient):
    response = await client.get("/connect")
    assert "mcpUrl" in response.text
    assert "8001" in response.text


@pytest.mark.asyncio
async def test_chat_api_requires_api_key(client: AsyncClient):
    response = await client.post(
        "/api/v1/chat",
        json={"messages": [{"role": "user", "content": "Hallo"}]},
    )
    assert response.status_code == 400
    data = response.json()
    assert "Schluessel" in data["detail"]


@pytest.mark.asyncio
async def test_execute_tool_list(client: AsyncClient):
    response = await client.post(
        "/api/v1/chat/execute-tool",
        json={"tool_name": "list_form_tools", "arguments": {}},
    )
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
