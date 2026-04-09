from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.exploration_job import ExplorationJob

router = APIRouter()


@router.get("/explore/{job_id}/status")
async def get_exploration_status(job_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ExplorationJob).where(ExplorationJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": str(job.id),
        "sourceUrl": job.source_url,
        "status": job.status,
        "progressLog": job.progress_log or [],
        "error": job.error,
        "formGraphId": str(job.form_graph_id) if job.form_graph_id else None,
        "createdAt": job.created_at.isoformat(),
    }
