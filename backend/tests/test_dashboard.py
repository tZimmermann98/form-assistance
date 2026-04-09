import pytest
from httpx import AsyncClient

from backend.app.models.form_graph import FormGraph, FormStatus


@pytest.mark.asyncio
async def test_dashboard_returns_200(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_contains_inertia_div(client: AsyncClient):
    response = await client.get("/")
    assert 'id="app"' in response.text
    assert "data-page" in response.text


@pytest.mark.asyncio
async def test_dashboard_renders_dashboard_component(client: AsyncClient):
    response = await client.get("/")
    assert '"Dashboard"' in response.text


@pytest.mark.asyncio
async def test_dashboard_shows_seeded_form(client: AsyncClient, db_session):
    form = FormGraph(
        form_id="TEST_001",
        title="Test Formular",
        source_url="https://example.com/test",
        status=FormStatus.REVIEW_PENDING,
        graph_data={"steps": []},
    )
    db_session.add(form)
    await db_session.commit()

    response = await client.get("/")
    assert response.status_code == 200
    assert "Test Formular" in response.text
