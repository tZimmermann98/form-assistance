from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.inertia_setup import InertiaDep
from backend.app.models.form_graph import FormGraph


router = APIRouter()


def _count_fields(graph_data: dict | None) -> int:
    if not graph_data or "steps" not in graph_data:
        return 0
    count = 0
    for step in graph_data["steps"]:
        for section in step.get("sections", []):
            count += len(section.get("fields", []))
    return count


@router.get("/")
async def dashboard(inertia: InertiaDep, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FormGraph).order_by(FormGraph.created_at.desc())
    )
    forms = result.scalars().all()

    return await inertia.render(
        "Dashboard",
        props={
            "forms": [
                {
                    "id": str(f.id),
                    "formId": f.form_id,
                    "title": f.title,
                    "sourceUrl": f.source_url,
                    "organization": f.organization,
                    "platform": f.platform,
                    "status": f.status,
                    "version": f.version,
                    "fieldCount": _count_fields(f.graph_data),
                    "exploredAt": f.explored_at.isoformat() if f.explored_at else None,
                    "approvedAt": f.approved_at.isoformat() if f.approved_at else None,
                    "createdAt": f.created_at.isoformat(),
                }
                for f in forms
            ],
        },
    )
