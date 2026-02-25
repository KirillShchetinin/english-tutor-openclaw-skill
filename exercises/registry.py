from __future__ import annotations

from exercises.base import Exercise

_registry: list[type[Exercise]] = []


def register_exercise(exercise_cls: type[Exercise]) -> type[Exercise]:
    """Decorator to register an exercise class."""
    if exercise_cls not in _registry:
        _registry.append(exercise_cls)
    return exercise_cls


def get_registry() -> list[type[Exercise]]:
    """Return a shallow copy of the registry."""
    return list(_registry)


def override_registry(classes: list[type[Exercise]]) -> None:
    """Replace registry contents. For testing only."""
    _registry.clear()
    _registry.extend(classes)
