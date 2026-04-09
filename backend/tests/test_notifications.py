"""Tests for the notification system."""

import pytest
from httpx import AsyncClient

from backend.app.models.notification import Notification


@pytest.fixture
async def sample_notifications(db_session):
    n1 = Notification(
        type="form_outdated",
        title_de="Formular veraltet",
        message_de="Das Formular hat sich geaendert.",
        read=False,
    )
    n2 = Notification(
        type="exploration_complete",
        title_de="Erkundung abgeschlossen",
        message_de="17 Felder in 4 Schritten.",
        read=True,
    )
    db_session.add(n1)
    db_session.add(n2)
    await db_session.commit()
    await db_session.refresh(n1)
    await db_session.refresh(n2)
    return [n1, n2]


@pytest.mark.asyncio
async def test_list_notifications(client: AsyncClient, sample_notifications):
    response = await client.get("/api/v1/notifications")
    assert response.status_code == 200
    data = response.json()
    assert data["unreadCount"] == 1
    assert len(data["notifications"]) == 2
    # Unread should come first
    assert data["notifications"][0]["read"] is False


@pytest.mark.asyncio
async def test_mark_read(client: AsyncClient, sample_notifications):
    unread = sample_notifications[0]
    response = await client.post(f"/api/v1/notifications/{unread.id}/read")
    assert response.status_code == 200

    # Verify it's now read
    response = await client.get("/api/v1/notifications")
    data = response.json()
    assert data["unreadCount"] == 0


@pytest.mark.asyncio
async def test_mark_all_read(client: AsyncClient, sample_notifications):
    response = await client.post("/api/v1/notifications/read-all")
    assert response.status_code == 200
    assert response.json()["marked"] >= 1

    response = await client.get("/api/v1/notifications")
    assert response.json()["unreadCount"] == 0


@pytest.mark.asyncio
async def test_empty_notifications(client: AsyncClient):
    response = await client.get("/api/v1/notifications")
    data = response.json()
    assert data["unreadCount"] == 0
    assert data["notifications"] == []
