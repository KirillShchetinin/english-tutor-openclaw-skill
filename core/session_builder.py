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


def build_exercises_by_names(names: list[str]) -> list[Exercise]:
    """Instantiate registered exercises matching the given names, preserving order.

    Unknown names are silently skipped (exercise may have been removed).
    """
    instances = [cls() for cls in get_registry()]
    by_name = {ex.name: ex for ex in instances}
    return [by_name[n] for n in names if n in by_name]
