import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExplorationJob(Base):
    __tablename__ = "exploration_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    form_graph_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_graphs.id"), nullable=True
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default=JobStatus.PENDING, nullable=False
    )
    progress_log: Mapped[list | None] = mapped_column(
        JSON, default=list, comment="Array of {step, message, timestamp}"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
