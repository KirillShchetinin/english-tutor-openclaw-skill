from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_DATA_PATH: Path = Path(
    os.environ.get("ENGLISH_TUTOR_DATA_PATH", "data/skills/english-tutor/")
)

SESSION_PUSH_TIMES: list[str] = ["09:00", "14:00", "20:00"]

MIN_SESSION_GAP_HOURS: int = 1

ABSENCE_NUDGE_DAYS: int = 2

PROFILE_REFRESH_INTERVAL: int = 5

EXERCISE_RETRY_ATTEMPTS: int = 1
