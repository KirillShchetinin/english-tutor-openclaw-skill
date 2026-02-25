from __future__ import annotations

from pathlib import Path

WORKSPACE_DATA_PATH: Path = Path("data/skills/english-tutor/")

SESSION_PUSH_TIMES: list[str] = ["09:00", "14:00", "20:00"]

MIN_SESSION_GAP_HOURS: int = 1

ABSENCE_NUDGE_DAYS: int = 2

PROFILE_REFRESH_INTERVAL: int = 5

EXERCISE_RETRY_ATTEMPTS: int = 1

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
