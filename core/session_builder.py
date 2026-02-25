from __future__ import annotations

from models import SessionState, UserProfile
from exercises.base import Exercise
import exercises  # noqa: F401 — triggers auto-discovery
from exercises.registry import get_registry


def build_session(state: SessionState, profile: UserProfile) -> list[Exercise]:
    """Build a session by instantiating all registered exercises.

    Returns empty list when no exercises are registered yet.
    """
    return [cls() for cls in get_registry()]
