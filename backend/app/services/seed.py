"""Seed the database with reference form graph data."""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from backend.app.database import Base, async_session, engine
from backend.app.models.form_graph import FormGraph, FormStatus


async def seed():
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    data_path = (
        Path(__file__).parent.parent.parent.parent
        / "reference-data"
        / "form-graph-vollmacht-ausweis.json"
    )
    graph_data = json.loads(data_path.read_text())

    async with async_session() as session:
        result = await session.execute(
            select(FormGraph).where(FormGraph.form_id == "KFAS_CQ00171")
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            print("Vollmacht form graph already seeded, skipping.")
            return

        form = FormGraph(
            form_id="KFAS_CQ00171",
            title="Vollmacht zur Abholung eines Ausweises / Passes",
            source_url="https://formulare.stadt-muenster.de/metaform/Form-Solutions/sid/assistant/KFAS_CQ00171",
            organization="Stadt Munster",
            platform="MACH formsolutions",
            status=FormStatus.REVIEW_PENDING,
            graph_data=graph_data,
        )
        session.add(form)
        await session.commit()
        print(f"Seeded Vollmacht form graph (id={form.id})")


if __name__ == "__main__":
    asyncio.run(seed())
