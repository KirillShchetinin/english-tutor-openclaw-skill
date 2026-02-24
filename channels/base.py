from __future__ import annotations

from abc import ABC, abstractmethod

from models import Message


class OutputChannel(ABC):
    @abstractmethod
    async def send(self, message: Message) -> None:
        """Send a message to the user."""
        ...
