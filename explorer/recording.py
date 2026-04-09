"""Playwright recording utilities for debugging.

Provides trace + video recording for both the explorer and executor.
Controlled by PLAYWRIGHT_RECORD env var (true/false, default false).

Recordings are saved to ./recordings/<type>/<id>/ with:
  - trace.zip  — Playwright trace (open at https://trace.playwright.dev)
  - videos/    — Screen recording .webm files
"""

import os
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

RECORDINGS_BASE = Path(__file__).parent.parent / "recordings"


def should_record() -> bool:
    """Check if recording is enabled via PLAYWRIGHT_RECORD env var."""
    return os.environ.get("PLAYWRIGHT_RECORD", "false").lower() in ("true", "1", "yes")


def get_recordings_dir(record_type: str, record_id: str) -> Path:
    """Create and return a timestamped recordings directory.

    Args:
        record_type: "explore" or "execute"
        record_id: Job ID or unique identifier

    Returns:
        Path to the recordings directory (created if needed)
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dir_path = RECORDINGS_BASE / record_type / f"{timestamp}_{record_id}"
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "videos").mkdir(exist_ok=True)
    return dir_path
