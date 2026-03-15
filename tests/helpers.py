"""Shared test utilities for english-tutor tests."""
from __future__ import annotations

from contextlib import contextmanager

from models import Message
from channels.base import OutputChannel
from exercises.registry import _registry, override_registry


class RecordingChannel(OutputChannel):
    def __init__(self):
        self.sent: list[Message] = []
        self.done_statuses: list[str] = []

    async def send(self, message: Message) -> str | None:
        token = f"msg-{len(self.sent)}"
        self.sent.append(message)
        return token

    async def done(self, status: str = "ok", **_kwargs) -> None:
        self.done_statuses.append(status)


@contextmanager
def registry_override(classes: list):
    """Temporarily replace the exercise registry; restores on exit."""
    original = _registry[:]
    override_registry(classes)
    try:
        yield
    finally:
        override_registry(original)
