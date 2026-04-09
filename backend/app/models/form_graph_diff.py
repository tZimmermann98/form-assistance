import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base


class FormGraphDiff(Base):
    __tablename__ = "form_graph_diffs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    form_graph_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_graphs.id"), nullable=False
    )
    old_version: Mapped[int] = mapped_column(Integer, nullable=False)
    new_version: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="none | cosmetic | structural | breaking",
    )
    diff_data: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Full diff result as JSON"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
