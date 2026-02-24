from __future__ import annotations

import json
import logging
from pathlib import Path

from models import SessionState, UserProfile

logger = logging.getLogger(__name__)

STATE_FILENAME = "session_state.json"
PROFILE_FILENAME = "user_profile.json"


def load_state(data_path: Path) -> SessionState:
    """Load session state from JSON. Missing file returns defaults. Corrupted raises."""
    path = data_path / STATE_FILENAME
    if not path.exists():
        return SessionState()
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Corrupted state file: {path}") from e
    return SessionState.from_dict(data)


def save_state(data_path: Path, state: SessionState) -> None:
    """Save session state. Creates directory if needed."""
    data_path.mkdir(parents=True, exist_ok=True)
    path = data_path / STATE_FILENAME
    tmp_path = path.with_suffix(".tmp")
    try:
        tmp_path.write_text(
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def load_profile(data_path: Path) -> UserProfile:
    """Load user profile from JSON. Missing file returns defaults. Corrupted raises."""
    path = data_path / PROFILE_FILENAME
    if not path.exists():
        return UserProfile()
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Corrupted profile file: {path}") from e
    return UserProfile.from_dict(data)


def save_profile(data_path: Path, profile: UserProfile) -> None:
    """Save user profile. Creates directory if needed."""
    data_path.mkdir(parents=True, exist_ok=True)
    path = data_path / PROFILE_FILENAME
    tmp_path = path.with_suffix(".tmp")
    try:
        tmp_path.write_text(
            json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
