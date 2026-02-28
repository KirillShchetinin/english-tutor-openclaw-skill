"""
Tests for SkillChannel output protocol.

Run from the english-tutor directory:
    python -m pytest tests/test_skill_channel.py -v
"""
from __future__ import annotations

import asyncio
import io
import json
import re
from datetime import datetime, timezone
from unittest.mock import patch

from models import Message, SessionState, UserProfile
from channels.skill_channel import SkillChannel
from core.entry import run_session
from core.state import save_state
from exercises.base import Exercise
from exercises.registry import _registry, override_registry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROTOCOL_RE = re.compile(r"^OClaw_SKILL\|([0-9a-zA-Z_-]+)\|(.+)$")


def _capture_stdout(coro):
    """Capture bytes written to sys.stdout.buffer via SkillChannel's raw write path."""
    buf = io.BytesIO()
    fake_stdout = io.TextIOWrapper(buf, encoding="utf-8", write_through=True)
    with patch("channels.skill_channel.sys.stdout", fake_stdout):
        asyncio.run(coro)
        fake_stdout.flush()
    return buf.getvalue().decode("utf-8")


def _parse_tagged_lines(output: str) -> list[dict]:
    """Extract and parse all OClaw_SKILL tagged lines from output.

    Lines matching the prefix but containing invalid JSON will raise
    json.JSONDecodeError — this is intentional in tests.
    """
    results = []
    for line in output.splitlines():
        m = PROTOCOL_RE.match(line)
        if m:
            results.append(json.loads(m.group(2)))
    return results


# ---------------------------------------------------------------------------
# SkillChannel unit tests
# ---------------------------------------------------------------------------


class TestSkillChannel:
    def test_line_format(self):
        """Each send() produces one line matching OClaw_SKILL|<8hex>|<json>."""
        channel = SkillChannel()
        msg = Message(type="text", content="hello")
        output = _capture_stdout(channel.send(msg))

        lines = output.strip().splitlines()
        assert len(lines) == 1
        m = PROTOCOL_RE.match(lines[0])
        assert m is not None, f"Line did not match protocol format: {lines[0]}"

    def test_json_parseability(self):
        """The JSON portion parses and matches Message.to_dict()."""
        channel = SkillChannel()
        msg = Message(type="text", content="test content", parse_mode="Markdown")
        output = _capture_stdout(channel.send(msg))

        payloads = _parse_tagged_lines(output)
        assert len(payloads) == 1
        assert payloads[0] == msg.to_dict()

    def test_parse_mode_none_omitted_from_json(self):
        """Messages with parse_mode=None must not emit a parse_mode key."""
        channel = SkillChannel()
        msg = Message(type="text", content="plain text")
        output = _capture_stdout(channel.send(msg))

        payloads = _parse_tagged_lines(output)
        assert "parse_mode" not in payloads[0]

    def test_multiple_messages(self):
        """Multiple sends produce multiple tagged lines, each with a unique invocation ID."""
        channel = SkillChannel()
        messages = [
            Message(type="text", content="one"),
            Message(type="text", content="two"),
            Message(type="text", content="three"),
        ]

        async def send_all():
            for msg in messages:
                await channel.send(msg)

        output = _capture_stdout(send_all())
        lines = [line for line in output.splitlines() if line.startswith("OClaw_SKILL|")]
        assert len(lines) == 3

        # Each line has a distinct invocation ID
        ids = []
        for line in lines:
            m = PROTOCOL_RE.match(line)
            assert m is not None
            ids.append(m.group(1))
        assert len(ids) == len(set(ids)), "Expected unique ID per message"

    def test_cyrillic_and_emoji(self):
        """Cyrillic text and emoji survive the JSON roundtrip."""
        channel = SkillChannel()
        content = "📚 Занятие готово! Слова: яблоко, книга"
        msg = Message(type="text", content=content)
        output = _capture_stdout(channel.send(msg))

        payloads = _parse_tagged_lines(output)
        assert len(payloads) == 1
        assert payloads[0]["content"] == content

    def test_newlines_in_content(self):
        """Newlines in content are JSON-escaped, keeping each message on one line."""
        channel = SkillChannel()
        content = "Line 1\nLine 2\nLine 3"
        msg = Message(type="text", content=content)
        output = _capture_stdout(channel.send(msg))

        tagged = [line for line in output.splitlines() if line.startswith("OClaw_SKILL|")]
        assert len(tagged) == 1  # still one line despite \n in content

        payloads = _parse_tagged_lines(output)
        assert payloads[0]["content"] == content

    def test_done_signal(self):
        """done() emits a tagged line with type=done and status."""
        channel = SkillChannel()
        output = _capture_stdout(channel.done(status="ok"))

        payloads = _parse_tagged_lines(output)
        assert len(payloads) == 1
        assert payloads[0]["type"] == "done"
        assert payloads[0]["status"] == "ok"

    def test_done_error_status(self):
        """done() with error status emits status=error."""
        channel = SkillChannel()
        output = _capture_stdout(channel.done(status="error"))

        payloads = _parse_tagged_lines(output)
        assert payloads[0]["status"] == "error"
        assert set(payloads[0].keys()) == {"type", "status"}

    def test_done_without_prior_send(self):
        """done() works as the only output (e.g. guard path)."""
        channel = SkillChannel()
        output = _capture_stdout(channel.done(status="ok"))

        payloads = _parse_tagged_lines(output)
        assert len(payloads) == 1
        assert payloads[0]["type"] == "done"

    def test_done_only_emits_status(self):
        """done() emits only type and status."""
        channel = SkillChannel()
        output = _capture_stdout(channel.done(status="ok"))

        payloads = _parse_tagged_lines(output)
        assert set(payloads[0].keys()) == {"type", "status"}

    def test_pipe_in_content(self):
        """Pipe characters in content do not break the protocol."""
        channel = SkillChannel()
        content = "Option A | Option B | Option C"
        msg = Message(type="text", content=content)
        output = _capture_stdout(channel.send(msg))

        # Parse using split("|", 2) — same rule the LLM uses
        line = output.strip()
        parts = line.split("|", 2)
        assert len(parts) == 3
        payload = json.loads(parts[2])
        assert payload["content"] == content


# ---------------------------------------------------------------------------
# Integration: run_session with SkillChannel
# ---------------------------------------------------------------------------


class TestSkillChannelIntegration:
    def test_session_produces_tagged_output_and_done(self, tmp_path):
        """Full session with SkillChannel emits tagged lines ending with done."""
        channel = SkillChannel()
        output = _capture_stdout(
            run_session(tmp_path, channel=channel, force=True)
        )

        payloads = _parse_tagged_lines(output)
        assert len(payloads) >= 2  # at least one exercise message + done

        done_payload = payloads[-1]
        assert done_payload["type"] == "done"
        assert done_payload["status"] == "ok"

        for p in payloads[:-1]:
            assert p["type"] == "text"
            assert "content" in p

    def test_guard_too_soon_emits_done(self, tmp_path):
        """Guard check (too soon) emits text message followed by done."""
        save_state(tmp_path, SessionState(
            sessions_completed=1,
            last_completed_at=datetime.now(timezone.utc).isoformat(),
        ))

        channel = SkillChannel()
        output = _capture_stdout(
            run_session(tmp_path, channel=channel, force=False)
        )

        payloads = _parse_tagged_lines(output)
        assert len(payloads) == 2
        assert payloads[0]["type"] == "text"
        assert "рано" in payloads[0]["content"]
        assert payloads[1]["type"] == "done"
        assert payloads[1]["status"] == "ok"

    def test_empty_session_emits_done(self, tmp_path):
        """Session with no exercises emits message + done with zero counts."""
        original = _registry[:]
        override_registry([])
        try:
            channel = SkillChannel()
            output = _capture_stdout(
                run_session(tmp_path, channel=channel, force=True)
            )

            payloads = _parse_tagged_lines(output)
            assert len(payloads) == 2
            assert payloads[0]["type"] == "text"
            assert payloads[1]["type"] == "done"
        finally:
            override_registry(original)
