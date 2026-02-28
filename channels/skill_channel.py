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

    def _tag(self, data: dict) -> str:
        return f"{_PREFIX}|{secrets.token_hex(4)}|{json.dumps(data, ensure_ascii=False)}\n"

    async def send(self, message: Message) -> None:
        sys.stdout.write(self._tag(message.to_dict()))

    async def done(self, status: str = "ok", **_kwargs) -> None:
        sys.stdout.write(self._tag({"type": "done", "status": status}))

    def __repr__(self) -> str:
        return "SkillChannel()"
