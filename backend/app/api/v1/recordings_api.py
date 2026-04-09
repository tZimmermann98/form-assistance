"""API for listing and downloading Playwright recordings."""

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

RECORDINGS_BASE = Path(__file__).parent.parent.parent.parent / "recordings"


@router.get("/recordings")
async def list_recordings():
    """List all available recordings (traces + videos)."""
    recordings = []

    for record_type in ("explore", "execute"):
        type_dir = RECORDINGS_BASE / record_type
        if not type_dir.exists():
            continue

        for session_dir in sorted(type_dir.iterdir(), reverse=True):
            if not session_dir.is_dir():
                continue

            entry = {
                "id": session_dir.name,
                "type": record_type,
                "has_trace": (session_dir / "trace.zip").exists(),
                "videos": [],
            }

            videos_dir = session_dir / "videos"
            if videos_dir.exists():
                entry["videos"] = [
                    v.name for v in videos_dir.iterdir()
                    if v.suffix in (".webm", ".mp4")
                ]

            recordings.append(entry)

    return {"recordings": recordings}


@router.get("/recordings/{record_type}/{session_id}/trace")
async def download_trace(record_type: str, session_id: str):
    """Download a Playwright trace file (.zip)."""
    if record_type not in ("explore", "execute"):
        raise HTTPException(status_code=400, detail="Invalid record type")

    trace_path = RECORDINGS_BASE / record_type / session_id / "trace.zip"
    if not trace_path.exists():
        raise HTTPException(status_code=404, detail="Trace not found")

    return FileResponse(
        path=str(trace_path),
        media_type="application/zip",
        filename=f"trace_{record_type}_{session_id}.zip",
    )


@router.get("/recordings/{record_type}/{session_id}/video/{filename}")
async def download_video(record_type: str, session_id: str, filename: str):
    """Download a recording video file."""
    if record_type not in ("explore", "execute"):
        raise HTTPException(status_code=400, detail="Invalid record type")

    # Sanitize filename to prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    video_path = RECORDINGS_BASE / record_type / session_id / "videos" / filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    return FileResponse(
        path=str(video_path),
        media_type="video/webm",
        filename=filename,
    )
