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
