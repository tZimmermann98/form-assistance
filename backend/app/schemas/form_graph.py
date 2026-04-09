from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class FormGraphSummary(BaseModel):
    id: UUID
    form_id: str | None
    title: str
    source_url: str
    organization: str
    platform: str
    status: str
    version: int
    explored_at: datetime | None
    approved_at: datetime | None
    created_at: datetime
    field_count: int = 0

    model_config = {"from_attributes": True}


class FormGraphRead(FormGraphSummary):
    graph_data: dict[str, Any] | None
    mcp_tool_spec: dict[str, Any] | None
    approved_by: str | None
    automation_notes: dict[str, Any] | None
    updated_at: datetime

    model_config = {"from_attributes": True}
