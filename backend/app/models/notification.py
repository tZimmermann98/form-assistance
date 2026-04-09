import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    form_graph_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_graphs.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="form_outdated | form_broken | form_degraded | exploration_complete | exploration_failed",
    )
    title_de: Mapped[str] = mapped_column(String(500), nullable=False)
    message_de: Mapped[str] = mapped_column(Text, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
