from __future__ import annotations

import sys

from channels.base import OutputChannel
from models import Message


class ConsoleChannel(OutputChannel):
    async def send(self, message: Message) -> None:
        prefix = f"[{message.type.upper()}]"
        line = f"{prefix} {message.content}"
        sys.stdout.buffer.write((line + "\n---\n").encode("utf-8", errors="replace"))
