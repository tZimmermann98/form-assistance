import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.inertia_setup import InertiaDep
from backend.app.models.exploration_job import ExplorationJob, JobStatus
from backend.app.models.form_graph import FormGraph, FormStatus
from backend.app.services.settings_service import get_llm_config
from explorer.agent import run_exploration

router = APIRouter()


class ExploreRequest(BaseModel):
    url: str


@router.get("/explore")
async def explore_page(inertia: InertiaDep):
    return await inertia.render("FormExplorer", props={})


@router.post("/explore")
async def start_exploration(
    body: ExploreRequest,
    db: AsyncSession = Depends(get_db),
):
    # Create FormGraph placeholder
    form_graph = FormGraph(
        title=f"Erkundung: {body.url}",
        source_url=body.url,
        status=FormStatus.EXPLORING,
    )
    db.add(form_graph)
    await db.flush()

    # Create ExplorationJob
    job = ExplorationJob(
        form_graph_id=form_graph.id,
        source_url=body.url,
        status=JobStatus.PENDING,
        progress_log=[],
    )
    db.add(job)
    await db.commit()

    # Load LLM config for real exploration (falls back to mock if no API key)
    llm_config = await get_llm_config(db)

    # Kick off exploration as background task
    asyncio.create_task(run_exploration(job.id, llm_config))

    return RedirectResponse(
        url=f"/explore/{job.id}",
        status_code=303,
    )


@router.get("/explore/{job_id}")
async def explore_progress_page(
    job_id: UUID,
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExplorationJob).where(ExplorationJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    form_graph_id = str(job.form_graph_id) if job.form_graph_id else None

    return await inertia.render(
        "FormExplorerProgress",
        props={
            "job": {
                "id": str(job.id),
                "sourceUrl": job.source_url,
                "status": job.status,
                "progressLog": job.progress_log or [],
                "error": job.error,
                "formGraphId": form_graph_id,
                "createdAt": job.created_at.isoformat(),
            },
        },
    )
