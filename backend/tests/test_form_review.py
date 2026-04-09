import pytest
from httpx import AsyncClient

from backend.app.models.form_graph import FormGraph, FormStatus


@pytest.fixture
async def seeded_form(db_session):
    form = FormGraph(
        form_id="TEST_001",
        title="Test Formular",
        source_url="https://example.com/test",
        status=FormStatus.REVIEW_PENDING,
        graph_data={
            "steps": [
                {
                    "step": 1,
                    "id": "step1",
                    "title": "Erster Schritt",
                    "description": "Beschreibung",
                    "sections": [
                        {
                            "section": "Abschnitt 1",
                            "group_rule": None,
                            "fields": [
                                {
                                    "label": "Vorname",
                                    "type": "text",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                    "navigation": {"next": None, "back": None},
                }
            ],
            "outcome": {
                "type": "print_and_sign",
                "description": "Test outcome",
                "submission_mode": "offline",
            },
        },
    )
    db_session.add(form)
    await db_session.commit()
    await db_session.refresh(form)
    return form


@pytest.mark.asyncio
async def test_form_review_returns_200(client: AsyncClient, seeded_form):
    response = await client.get(f"/forms/{seeded_form.id}")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_form_review_renders_component(client: AsyncClient, seeded_form):
    response = await client.get(f"/forms/{seeded_form.id}")
    assert '"FormReview"' in response.text


@pytest.mark.asyncio
async def test_form_review_contains_graph_data(client: AsyncClient, seeded_form):
    response = await client.get(f"/forms/{seeded_form.id}")
    assert "Erster Schritt" in response.text
    assert "Vorname" in response.text


@pytest.mark.asyncio
async def test_form_review_404_for_missing(client: AsyncClient):
    response = await client.get("/forms/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_approve_form(client: AsyncClient, seeded_form):
    response = await client.post(
        f"/forms/{seeded_form.id}/approve",
        follow_redirects=False,
    )
    # Inertia back() returns a redirect
    assert response.status_code in (303, 307)


@pytest.mark.asyncio
async def test_approve_updates_status(client: AsyncClient, seeded_form, db_session):
    await client.post(
        f"/forms/{seeded_form.id}/approve",
        follow_redirects=False,
    )
    await db_session.refresh(seeded_form)
    assert seeded_form.status == FormStatus.APPROVED
    assert seeded_form.approved_at is not None
