from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.inertia_setup import InertiaDep
from backend.app.models.form_graph import FormGraph, FormStatus
from backend.app.models.form_graph_diff import FormGraphDiff

router = APIRouter()


def _count_fields(graph_data: dict | None) -> int:
    if not graph_data or "steps" not in graph_data:
        return 0
    count = 0
    for step in graph_data["steps"]:
        for section in step.get("sections", []):
            count += len(section.get("fields", []))
    return count


async def _get_latest_diff(db: AsyncSession, form_graph_id) -> dict | None:
    """Get the latest diff for this form, if any."""
    result = await db.execute(
        select(FormGraphDiff)
        .where(FormGraphDiff.form_graph_id == form_graph_id)
        .order_by(FormGraphDiff.created_at.desc())
        .limit(1)
    )
    diff = result.scalar_one_or_none()
    if diff:
        return diff.diff_data
    return None


@router.get("/forms/{form_id}")
async def form_review(form_id: UUID, inertia: InertiaDep, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FormGraph).where(FormGraph.id == form_id))
    form = result.scalar_one_or_none()
    if form is None:
        raise HTTPException(status_code=404, detail="Form not found")

    diff = await _get_latest_diff(db, form.id)

    return await inertia.render(
        "FormReview",
        props={
            "form": {
                "id": str(form.id),
                "formId": form.form_id,
                "title": form.title,
                "sourceUrl": form.source_url,
                "organization": form.organization,
                "platform": form.platform,
                "status": form.status,
                "version": form.version,
                "fieldCount": _count_fields(form.graph_data),
                "exploredAt": form.explored_at.isoformat() if form.explored_at else None,
                "approvedAt": form.approved_at.isoformat() if form.approved_at else None,
                "approvedBy": form.approved_by,
                "createdAt": form.created_at.isoformat(),
            },
            "graph": form.graph_data,
            "diff": diff,
        },
    )


@router.post("/forms/{form_id}/approve")
async def approve_form(form_id: UUID, inertia: InertiaDep, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FormGraph).where(FormGraph.id == form_id))
    form = result.scalar_one_or_none()
    if form is None:
        raise HTTPException(status_code=404, detail="Form not found")

    form.status = FormStatus.APPROVED
    form.approved_at = datetime.utcnow()
    form.approved_by = "admin"  # TODO: real user auth
    form.version = (form.version or 1) + 1
    await db.commit()

    return RedirectResponse(
        url=f"/forms/{form_id}",
        status_code=303,
    )
