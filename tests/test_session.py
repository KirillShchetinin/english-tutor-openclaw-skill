"""
Tests for session flow: builder, executor, entry, and console channel.

Run from the english-tutor directory:
    python -m pytest tests/test_session.py -v
"""
from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from models import Message, SessionState, UserProfile
from channels.base import OutputChannel
from exercises.base import Exercise
from exercises.registry import _registry, override_registry
from core.session_executor import SessionExecutor
from core.entry import run_session
from core.state import load_state, save_state
from config import ABSENCE_NUDGE_DAYS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class RecordingChannel(OutputChannel):
    def __init__(self):
        self.sent: list[Message] = []

    async def send(self, message: Message) -> None:
        self.sent.append(message)


def _make_exercise(name: str, messages=None, raises=None):
    if messages is None:
        messages = [Message(type="text", content="hello")]

    class E(Exercise):
        @property
        def name(self_):
            return name

        async def get_content(self_, profile):
            if raises:
                raise raises
            return messages

    return E()


# ---------------------------------------------------------------------------
# core.session_builder
# ---------------------------------------------------------------------------


class TestBuildSession:
    def test_build_session(self):
        """Empty registry returns []; registered exercise is instantiated."""
        from core import session_builder

        original = _registry[:]
        try:
            override_registry([])
            assert session_builder.build_session(SessionState(), UserProfile()) == []

            class DummyExercise(Exercise):
                @property
                def name(self):
                    return "dummy"

                async def get_content(self, profile):
                    return []

            override_registry([DummyExercise])
            result = session_builder.build_session(SessionState(), UserProfile())
            assert len(result) == 1
            assert isinstance(result[0], DummyExercise)
        finally:
            override_registry(original)


# ---------------------------------------------------------------------------
# core.session_executor
# ---------------------------------------------------------------------------


class TestSessionExecutor:
    def test_success_sends_messages_and_returns_result(self):
        """Successful exercise: messages forwarded to channel, result is success."""
        channel = RecordingChannel()
        msgs = [Message(type="text", content="A"), Message(type="text", content="B")]
        ex = _make_exercise("vocab", messages=msgs)
        results = asyncio.run(SessionExecutor(channel).execute([ex], UserProfile()))

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].exercise_name == "vocab"
        assert results[0].message_count == 2
        assert len(channel.sent) == 2
        assert channel.sent[0].content == "A"

    def test_failure_returns_failure_result(self):
        channel = RecordingChannel()
        ex = _make_exercise("bad_ex", raises=ValueError("boom"))
        results = asyncio.run(SessionExecutor(channel).execute([ex], UserProfile()))

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].exercise_name == "bad_ex"

    def test_multiple_and_empty(self):
        """Empty list returns []; multiple exercises all run."""
        channel = RecordingChannel()
        executor = SessionExecutor(channel)

        assert asyncio.run(executor.execute([], UserProfile())) == []

        exs = [_make_exercise(f"ex{i}") for i in range(3)]
        results = asyncio.run(executor.execute(exs, UserProfile()))
        assert len(results) == 3
        assert all(r.success for r in results)


# ---------------------------------------------------------------------------
# core.entry — guard logic and session flow
# ---------------------------------------------------------------------------


class TestRunSession:
    def test_force_skips_guard_and_completes(self, tmp_path):
        channel = RecordingChannel()
        asyncio.run(run_session(tmp_path, channel=channel, force=True))
        assert load_state(tmp_path).sessions_completed == 1

    def test_too_soon_guard_blocks_run(self, tmp_path):
        """Second run within MIN_SESSION_GAP_HOURS without --force should skip."""
        save_state(tmp_path, SessionState(
            sessions_completed=1,
            last_completed_at=datetime.now(timezone.utc).isoformat(),
        ))

        channel = RecordingChannel()
        asyncio.run(run_session(tmp_path, channel=channel, force=False))

        assert len(channel.sent) == 1
        assert load_state(tmp_path).sessions_completed == 1

    def test_no_exercises_sends_message_and_increments(self, tmp_path):
        """With no exercises registered, session still completes and increments counter."""
        original = _registry[:]
        override_registry([])
        try:
            channel = RecordingChannel()
            asyncio.run(run_session(tmp_path, channel=channel, force=True))
            assert len(channel.sent) == 1
            assert load_state(tmp_path).sessions_completed == 1
        finally:
            override_registry(original)

    def test_absence_nudge_increments_skipped(self, tmp_path):
        """If last session was > ABSENCE_NUDGE_DAYS ago, sends nudge and increments skipped."""
        old_time = datetime.now(timezone.utc) - timedelta(days=ABSENCE_NUDGE_DAYS + 1)
        save_state(tmp_path, SessionState(
            sessions_completed=1,
            last_completed_at=old_time.isoformat(),
        ))

        channel = RecordingChannel()
        asyncio.run(run_session(tmp_path, channel=channel, force=False))

        assert len(channel.sent) == 1
        new_state = load_state(tmp_path)
        assert new_state.sessions_skipped == 1
        assert new_state.sessions_completed == 1


# ---------------------------------------------------------------------------
# channels.console
# ---------------------------------------------------------------------------


class TestConsoleChannel:
    def test_send_outputs_utf8_with_type_prefix(self):
        """ConsoleChannel writes UTF-8 with [TYPE] prefix, handles Cyrillic/emoji."""
        from channels.console import ConsoleChannel

        buf = io.BytesIO()
        channel = ConsoleChannel()

        fake_stdout = io.TextIOWrapper(buf, encoding="utf-8")
        with patch("sys.stdout", fake_stdout):
            asyncio.run(channel.send(Message(type="text", content="📚 Занятие готово")))
        fake_stdout.flush()

        output = buf.getvalue().decode("utf-8")
        assert "[TEXT]" in output
        assert "Занятие готово" in output
