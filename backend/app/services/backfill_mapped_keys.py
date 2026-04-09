"""Backfill mapped_key for existing form graphs.

Adds deterministic mapped_key values to all fields in existing graph_data
that don't have them yet. Run once after deploying the mapped_key feature.

Usage:
    docker compose -f docker-compose.dev.yml exec backend python -m backend.app.services.backfill_mapped_keys
"""

import asyncio
import logging
import re

from sqlalchemy import select

from backend.app.database import async_session
from backend.app.models.form_graph import FormGraph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert German text to a snake_case slug."""
    slug = text.lower().strip()
    for old, new in [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]:
        slug = slug.replace(old, new)
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")[:40]


def backfill_graph(graph_data: dict) -> bool:
    """Add mapped_key to all fields in a graph_data dict.

    Returns True if any changes were made.
    """
    if not graph_data:
        return False

    all_steps = graph_data.get("steps", [])
    # Also include branch path steps
    for bp in graph_data.get("branch_paths", []):
        all_steps = all_steps + bp.get("steps", [])

    changed = False
    seen_keys: set[str] = set()

    for step in all_steps:
        step_id = step.get("id", f"step_{step.get('step', 0)}")
        if step_id == "consent":
            continue

        for section in step.get("sections", []):
            section_name = section.get("section", "")
            for field in section.get("fields", []):
                if field.get("mapped_key"):
                    seen_keys.add(field["mapped_key"])
                    continue

                label = field.get("label", "unknown")
                label_slug = _slugify(label)

                # Generate key with section context if label is common
                if section_name:
                    key = f"{_slugify(section_name)}_{label_slug}"
                else:
                    key = f"{_slugify(step_id)}_{label_slug}"

                # Deduplicate
                final_key = key
                suffix = 2
                while final_key in seen_keys:
                    final_key = f"{key}_{suffix}"
                    suffix += 1

                field["mapped_key"] = final_key
                seen_keys.add(final_key)
                changed = True
                logger.info("  Added mapped_key '%s' for field '%s'", final_key, label)

    return changed


async def main():
    async with async_session() as session:
        result = await session.execute(select(FormGraph))
        forms = result.scalars().all()

        updated = 0
        for form in forms:
            if not form.graph_data:
                continue

            logger.info("Processing form: %s (id=%s)", form.title, form.id)
            if backfill_graph(form.graph_data):
                # Force SQLAlchemy to detect the JSONB change
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(form, "graph_data")
                updated += 1

        if updated > 0:
            await session.commit()
            logger.info("Updated %d form graph(s) with mapped_key values", updated)
        else:
            logger.info("No forms needed backfilling")


if __name__ == "__main__":
    asyncio.run(main())
