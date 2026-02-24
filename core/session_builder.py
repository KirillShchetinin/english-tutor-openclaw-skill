from __future__ import annotations

from models import SessionState, UserProfile
from exercises.base import Exercise

# Exercise registry - exercises register here when implemented
_registry: list[type[Exercise]] = []


def register_exercise(exercise_cls: type[Exercise]) -> type[Exercise]:
    """Decorator to register an exercise class."""
    _registry.append(exercise_cls)
    return exercise_cls


def build_session(state: SessionState, profile: UserProfile) -> list[Exercise]:
    """Build a session by instantiating all registered exercises.

    Returns empty list when no exercises are registered yet.
    """
    return [cls() for cls in _registry]
