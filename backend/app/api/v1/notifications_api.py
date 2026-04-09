from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.services.notification_service import (
    get_notifications,
    get_unread_count,
    mark_all_read,
    mark_read,
)

router = APIRouter()


@router.get("/notifications")
async def list_notifications(db: AsyncSession = Depends(get_db)):
    notifications = await get_notifications(db, limit=20)
    unread = await get_unread_count(db)
    return {"notifications": notifications, "unreadCount": unread}


@router.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: UUID, db: AsyncSession = Depends(get_db)):
    await mark_read(db, notification_id)
    return {"status": "ok"}


@router.post("/notifications/read-all")
async def read_all_notifications(db: AsyncSession = Depends(get_db)):
    count = await mark_all_read(db)
    return {"status": "ok", "marked": count}
