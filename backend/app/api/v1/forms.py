import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.exploration_job import ExplorationJob, JobStatus
from backend.app.models.form_graph import FormGraph, FormStatus

router = APIRouter()


@router.get("/forms")
async def list_forms(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FormGraph).order_by(FormGraph.created_at.desc())
    )
    forms = result.scalars().all()
    return [
        {
            "id": str(f.id),
            "form_id": f.form_id,
            "title": f.title,
            "status": f.status,
        }
        for f in forms
    ]


@router.get("/forms/{form_id}/graph")
async def get_form_graph(form_id: UUID, db: AsyncSession = Depends(get_db)):
    """Returns the form graph — used by the executor."""
    result = await db.execute(select(FormGraph).where(FormGraph.id == form_id))
    form = result.scalar_one_or_none()
    if form is None:
        raise HTTPException(status_code=404, detail="Form not found")
    return form.graph_data


@router.delete("/forms/{form_id}")
async def delete_form(form_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a form and its associated exploration jobs."""
    result = await db.execute(select(FormGraph).where(FormGraph.id == form_id))
    form = result.scalar_one_or_none()
    if form is None:
        raise HTTPException(status_code=404, detail="Form not found")

    # Delete associated exploration jobs first
    jobs_result = await db.execute(
        select(ExplorationJob).where(ExplorationJob.form_graph_id == form_id)
    )
    for job in jobs_result.scalars().all():
        await db.delete(job)

    await db.delete(form)
    await db.commit()
    return {"status": "deleted", "id": str(form_id)}


@router.post("/forms/{form_id}/re-explore")
async def trigger_re_exploration(form_id: UUID, db: AsyncSession = Depends(get_db)):
    """Trigger re-exploration for change detection."""
    result = await db.execute(select(FormGraph).where(FormGraph.id == form_id))
    form = result.scalar_one_or_none()
    if form is None:
        raise HTTPException(status_code=404, detail="Form not found")

    # Set status to degraded
    form.status = FormStatus.DEGRADED
    await db.flush()

    # Create re-exploration job
    job = ExplorationJob(
        form_graph_id=form.id,
        source_url=form.source_url,
        status=JobStatus.PENDING,
        progress_log=[],
    )
    db.add(job)
    await db.commit()

    # Start exploration in background
    from backend.app.services.settings_service import get_llm_config
    from explorer.agent import run_exploration
    llm_config = await get_llm_config(db)
    asyncio.create_task(run_exploration(job.id, llm_config))

    return {
        "status": "re-exploration triggered",
        "job_id": str(job.id),
        "form_status": "degraded",
    }
