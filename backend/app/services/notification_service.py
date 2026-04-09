"""Service for creating and querying notifications."""

import logging
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.notification import Notification

logger = logging.getLogger(__name__)


async def create_notification(
    db: AsyncSession,
    type: str,
    title_de: str,
    message_de: str,
    form_graph_id: UUID | None = None,
) -> Notification:
    """Create a new notification."""
    notif = Notification(
        form_graph_id=form_graph_id,
        type=type,
        title_de=title_de,
        message_de=message_de,
    )
    db.add(notif)
    await db.commit()
    await db.refresh(notif)
    return notif


async def get_notifications(db: AsyncSession, limit: int = 20) -> list[dict]:
    """Get recent notifications, unread first."""
    result = await db.execute(
        select(Notification)
        .order_by(Notification.read.asc(), Notification.created_at.desc())
        .limit(limit)
    )
    notifications = result.scalars().all()
    return [
        {
            "id": str(n.id),
            "formGraphId": str(n.form_graph_id) if n.form_graph_id else None,
            "type": n.type,
            "titleDe": n.title_de,
            "messageDe": n.message_de,
            "read": n.read,
            "createdAt": n.created_at.isoformat(),
        }
        for n in notifications
    ]


async def get_unread_count(db: AsyncSession) -> int:
    """Get count of unread notifications."""
    from sqlalchemy import func
    result = await db.execute(
        select(func.count(Notification.id)).where(Notification.read == False)
    )
    return result.scalar() or 0


async def mark_read(db: AsyncSession, notification_id: UUID) -> None:
    """Mark a single notification as read."""
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id)
        .values(read=True)
    )
    await db.commit()


async def mark_all_read(db: AsyncSession) -> int:
    """Mark all unread notifications as read. Returns count."""
    result = await db.execute(
        update(Notification)
        .where(Notification.read == False)
        .values(read=True)
    )
    await db.commit()
    return result.rowcount  # type: ignore
