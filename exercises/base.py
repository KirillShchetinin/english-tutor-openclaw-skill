from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from channels.base import OutputChannel
from models import UserProfile


@dataclass
class RunResult:
    completed: bool
    reason: str | None = None
    stage: tuple[int, int] | None = None  # (current, total) e.g. (3, 5)
    waiting_for_user: bool = False


class Exercise(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this exercise type."""
        ...

    @abstractmethod
    async def run(self, channel: OutputChannel, profile: UserProfile) -> RunResult:
        """Run the exercise, sending output via channel. Returns completion result."""
        ...



class InteractiveExercise(Exercise):
    """Exercise that supports multi-turn interaction via reply().

    The exercise must persist enough context during run() to handle a later
    reply() call — the framework only stores which exercise to resume.
    """

    @abstractmethod
    async def reply(self, user_input: str, channel: OutputChannel, profile: UserProfile) -> RunResult:
        """Handle user's reply during a resumed session."""
        ...
