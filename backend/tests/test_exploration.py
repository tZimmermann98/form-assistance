import pytest
from httpx import AsyncClient

from backend.app.models.exploration_job import ExplorationJob, JobStatus
from backend.app.models.form_graph import FormGraph, FormStatus


@pytest.fixture
async def running_job(db_session):
    form = FormGraph(
        title="Test Exploration",
        source_url="https://example.com/form",
        status=FormStatus.EXPLORING,
    )
    db_session.add(form)
    await db_session.flush()

    job = ExplorationJob(
        form_graph_id=form.id,
        source_url="https://example.com/form",
        status=JobStatus.RUNNING,
        progress_log=[
            {"step": 1, "message": "Loading...", "timestamp": "2026-01-01T00:00:00Z"},
        ],
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job


@pytest.mark.asyncio
async def test_explore_page_returns_200(client: AsyncClient):
    response = await client.get("/explore")
    assert response.status_code == 200
    assert '"FormExplorer"' in response.text


@pytest.mark.asyncio
async def test_post_explore_creates_job(client: AsyncClient, db_session):
    response = await client.post(
        "/explore",
        json={"url": "https://example.com/test-form"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/explore/" in response.headers["location"]


@pytest.mark.asyncio
async def test_explore_progress_page(client: AsyncClient, running_job):
    response = await client.get(f"/explore/{running_job.id}")
    assert response.status_code == 200
    assert '"FormExplorerProgress"' in response.text


@pytest.mark.asyncio
async def test_explore_status_api(client: AsyncClient, running_job):
    response = await client.get(f"/api/v1/explore/{running_job.id}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert len(data["progressLog"]) == 1
    assert data["progressLog"][0]["message"] == "Loading..."


@pytest.mark.asyncio
async def test_explore_status_404(client: AsyncClient):
    response = await client.get(
        "/api/v1/explore/00000000-0000-0000-0000-000000000000/status"
    )
    assert response.status_code == 404
