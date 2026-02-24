from __future__ import annotations

from channels.base import OutputChannel
from models import Message


class TelegramChannel(OutputChannel):
    async def send(self, message: Message) -> None:
        raise NotImplementedError(
            "TelegramChannel requires OpenClaw platform integration. "
            "Use ConsoleChannel with --test for local development."
        )
