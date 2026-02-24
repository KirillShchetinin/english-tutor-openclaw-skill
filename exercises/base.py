from __future__ import annotations

from abc import ABC, abstractmethod

from models import Message, UserProfile


class Exercise(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this exercise type."""
        ...

    @abstractmethod
    async def get_content(self, profile: UserProfile) -> list[Message]:
        """Generate exercise content. Returns list of messages to send."""
        ...
