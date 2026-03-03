from __future__ import annotations

import json
import secrets
import sys

from channels.base import OutputChannel
from models import Message

_PREFIX = "OClaw_SKILL"


class SkillChannel(OutputChannel):
    """Output channel for LLM orchestrator consumption.

    Emits tagged lines to stdout in the format:
        OClaw_SKILL|<invocation_id>|<json>

    The LLM parses only lines with the OClaw_SKILL prefix; all other
    stdout/stderr output is ignored.
    """

    def _tag(self, data: dict) -> tuple[str, str]:
        token = secrets.token_hex(4)
        line = f"{_PREFIX}|{token}|{json.dumps(data, ensure_ascii=False)}\n"
        return line, token

    async def send(self, message: Message) -> str:
        line, token = self._tag(message.to_dict())
        sys.stdout.write(line)
        return token

    async def done(self, status: str = "ok", **kwargs) -> str:
        payload = {"type": "done", "status": status, **kwargs}
        line, token = self._tag(payload)
        sys.stdout.write(line)
        return token

    def __repr__(self) -> str:
        return "SkillChannel()"
