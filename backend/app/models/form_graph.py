import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class FormStatus(str, Enum):
    EXPLORING = "exploring"
    EXPLORATION_FAILED = "exploration_failed"
    REVIEW_PENDING = "review_pending"
    APPROVED = "approved"
    OUTDATED = "outdated"
    DEGRADED = "degraded"
    BROKEN = "broken"


class FormGraph(Base):
    __tablename__ = "form_graphs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    form_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="External ID like KFAS_CQ00171"
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    organization: Mapped[str] = mapped_column(
        String(200), default="Stadt Munster"
    )
    platform: Mapped[str] = mapped_column(
        String(100), default="MACH formsolutions"
    )

    status: Mapped[str] = mapped_column(
        String(50), default=FormStatus.EXPLORING, nullable=False
    )

    # The actual form graph — stored as JSON
    graph_data: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Full form graph: steps, fields, sections, conditional logic"
    )

    # Generated MCP tool spec — stored as JSON
    mcp_tool_spec: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Generated MCP tool definition"
    )

    # Lifecycle
    explored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    # Automation metadata
    automation_notes: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Platform quirks, login requirements, etc."
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
