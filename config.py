from __future__ import annotations

import json
from pathlib import Path

from models import StudentLevel

WORKSPACE_DATA_PATH: Path = Path("data/skills/english-tutor/")
SESSION_PUSH_TIMES: list[str] = ["09:00", "14:00", "20:00"]
ABSENCE_NUDGE_DAYS: int = 2
PROFILE_REFRESH_INTERVAL: int = 5
EXERCISE_RETRY_ATTEMPTS: int = 1
RESUME_CLOSE_TO_NEXT_MINUTES: int = 30

# Runtime data path — set by entry.py at session start, allows test isolation.
_active_data_path: Path | None = None


def get_data_path() -> Path:
    """Return the active data path (set at runtime) or the default."""
    if _active_data_path is not None:
        return _active_data_path
    return WORKSPACE_DATA_PATH


def set_data_path(path: Path) -> None:
    """Set the active data path. Called by run_session() at startup."""
    global _active_data_path
    _active_data_path = path


def reset_data_path() -> None:
    """Reset the active data path to the default. Called after session ends."""
    global _active_data_path
    _active_data_path = None


def get_student_level() -> StudentLevel:
    """Read student_level from <data_path>/config.json. Raises if missing."""
    path = get_data_path() / "config.json"
    if not path.exists():
        raise RuntimeError(
            f"config.json not found at {path} "
            "— OpenClaw must write it before the first session"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if "student_level" not in data:
        raise RuntimeError(
            f"'student_level' key missing in {path} "
            "— OpenClaw must set it before the first session"
        )
    return StudentLevel.parse(data["student_level"])
