from __future__ import annotations

from abc import ABC, abstractmethod

from models import Message


class OutputChannel(ABC):
    @abstractmethod
    async def send(self, message: Message) -> None:
        """Send a message to the user."""
        ...

    async def done(self, status: str = "ok", **_kwargs) -> None:
        """Signal session completion. Override in protocol channels."""