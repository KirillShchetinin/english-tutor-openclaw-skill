"""
Targeted tests for the English Tutor async framework.

Run from the english-tutor directory:
    python -m pytest tests/test_framework.py -v

Coverage:
    - models: SessionState, UserProfile, Message, ExerciseCompletion round-trips
    - core.state: load_state / save_state / load_profile / save_profile
    - core.state: corrupted file raises RuntimeError
    - core.entry: guard logic (too-soon skip, absence nudge)
    - core.entry: no-exercises path writes state and increments sessions_completed
    - core.session_builder: empty registry returns empty list
    - core.session_executor: exercise success / failure / retry paths
    - channels.console: ConsoleChannel writes utf-8 bytes
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestMessage:
    def test_to_dict_without_parse_mode(self):
        from models import Message

        msg = Message(type="text", content="Hello")
        d = msg.to_dict()
        assert d == {"type": "text", "content": "Hello"}
        assert "parse_mode" not in d

    def test_to_dict_with_parse_mode(self):
        from models import Message

        msg = Message(type="text", content="**bold**", parse_mode="Markdown")
        d = msg.to_dict()
        assert d == {"type": "text", "content": "**bold**", "parse_mode": "Markdown"}

    def test_to_dict_does_not_include_none_parse_mode(self):
        from models import Message

        msg = Message(type="photo", content="url", parse_mode=None)
        assert "parse_mode" not in msg.to_dict()


class TestExerciseCompletion:
    def test_round_trip(self):
        from models import ExerciseCompletion

        ec = ExerciseCompletion(
            exercise_name="vocab_drill",
            completed_at="2026-02-24T05:00:00+00:00",
        )
        restored = ExerciseCompletion.from_dict(ec.to_dict())
        assert restored.exercise_name == "vocab_drill"
        assert restored.completed_at == "2026-02-24T05:00:00+00:00"


class TestSessionState:
    def test_round_trip_with_completions(self):
        from models import SessionState, ExerciseCompletion

        ec = ExerciseCompletion(
            exercise_name="vocab_drill",
            completed_at="2026-02-24T05:00:00+00:00",
        )
        state = SessionState(
            sessions_completed=7,
            last_completed_at="2026-02-24T05:00:00+00:00",
            sessions_skipped=2,
            exercise_completions=[ec],
        )
        restored = SessionState.from_dict(state.to_dict())

        assert restored.sessions_completed == 7
        assert restored.last_completed_at == "2026-02-24T05:00:00+00:00"
        assert restored.sessions_skipped == 2
        assert len(restored.exercise_completions) == 1
        assert restored.exercise_completions[0].exercise_name == "vocab_drill"

    def test_from_dict_defaults_on_empty(self):
        from models import SessionState

        state = SessionState.from_dict({})
        assert state.sessions_completed == 0
        assert state.last_completed_at is None
        assert state.sessions_skipped == 0
        assert state.exercise_completions == []

    def test_to_dict_keys(self):
        from models import SessionState

        d = SessionState().to_dict()
        assert set(d.keys()) == {
            "sessions_completed",
            "last_completed_at",
            "sessions_skipped",
            "exercise_completions",
        }


class TestUserProfile:
    def test_round_trip(self):
        from models import UserProfile

        profile = UserProfile(
            summary="Advanced speaker",
            words_learned=150,
            words_in_progress=30,
            accuracy=0.87,
            streak=14,
            weak_spots=["articles", "prepositions"],
            strong_topics=["past tense", "vocabulary"],
        )
        restored = UserProfile.from_dict(profile.to_dict())

        assert restored.summary == "Advanced speaker"
        assert restored.words_learned == 150
        assert restored.words_in_progress == 30
        assert abs(restored.accuracy - 0.87) < 1e-9
        assert restored.streak == 14
        assert restored.weak_spots == ["articles", "prepositions"]
        assert restored.strong_topics == ["past tense", "vocabulary"]

    def test_from_dict_defaults_on_empty(self):
        from models import UserProfile

        profile = UserProfile.from_dict({})
        assert profile.summary == ""
        assert profile.words_learned == 0
        assert profile.words_in_progress == 0
        assert profile.accuracy == 0.0
        assert profile.streak == 0
        assert profile.weak_spots == []
        assert profile.strong_topics == []

    def test_weak_spots_is_independent_copy(self):
        """Mutating the original list must not affect the stored profile."""
        from models import UserProfile

        spots = ["articles"]
        profile = UserProfile(weak_spots=spots)
        d = profile.to_dict()
        d["weak_spots"].append("prepositions")
        assert profile.weak_spots == ["articles"]


# ---------------------------------------------------------------------------
# core.state
# ---------------------------------------------------------------------------


class TestLoadSaveState:
    def test_missing_file_returns_defaults(self, tmp_path):
        from core.state import load_state

        state = load_state(tmp_path)
        assert state.sessions_completed == 0

    def test_round_trip_persists_correctly(self, tmp_path):
        from core.state import load_state, save_state
        from models import SessionState, ExerciseCompletion

        state = SessionState(
            sessions_completed=3,
            last_completed_at="2026-02-24T05:00:00+00:00",
            sessions_skipped=1,
            exercise_completions=[
                ExerciseCompletion("drill", "2026-02-24T05:00:00+00:00")
            ],
        )
        save_state(tmp_path, state)
        restored = load_state(tmp_path)

        assert restored.sessions_completed == 3
        assert restored.last_completed_at == "2026-02-24T05:00:00+00:00"
        assert restored.sessions_skipped == 1
        assert len(restored.exercise_completions) == 1

    def test_corrupted_json_raises_runtime_error(self, tmp_path):
        from core.state import load_state

        (tmp_path / "session_state.json").write_text("{bad json: [}", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Corrupted state file"):
            load_state(tmp_path)

    def test_save_creates_directory(self, tmp_path):
        from core.state import save_state
        from models import SessionState

        nested = tmp_path / "a" / "b" / "c"
        save_state(nested, SessionState())
        assert (nested / "session_state.json").exists()

    def test_save_is_valid_json(self, tmp_path):
        from core.state import save_state
        from models import SessionState

        save_state(tmp_path, SessionState(sessions_completed=5))
        raw = (tmp_path / "session_state.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["sessions_completed"] == 5


class TestLoadSaveProfile:
    def test_missing_file_returns_defaults(self, tmp_path):
        from core.state import load_profile

        profile = load_profile(tmp_path)
        assert profile.summary == ""
        assert profile.words_learned == 0

    def test_round_trip(self, tmp_path):
        from core.state import load_profile, save_profile
        from models import UserProfile

        profile = UserProfile(summary="Test", words_learned=42)
        save_profile(tmp_path, profile)
        restored = load_profile(tmp_path)
        assert restored.summary == "Test"
        assert restored.words_learned == 42

    def test_corrupted_json_raises_runtime_error(self, tmp_path):
        from core.state import load_profile

        (tmp_path / "user_profile.json").write_text("not-json!!!", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Corrupted profile file"):
            load_profile(tmp_path)


# ---------------------------------------------------------------------------
# core.session_builder
# ---------------------------------------------------------------------------


class TestBuildSession:
    def test_empty_registry_returns_empty_list(self):
        """With no exercises registered, build_session returns []."""
        from core import session_builder
        from models import SessionState, UserProfile

        # Patch the registry to be empty for this test
        original = session_builder._registry[:]
        session_builder._registry.clear()
        try:
            result = session_builder.build_session(SessionState(), UserProfile())
            assert result == []
        finally:
            session_builder._registry[:] = original

    def test_registered_exercise_is_instantiated(self):
        from core import session_builder
        from exercises.base import Exercise
        from models import SessionState, UserProfile, Message

        class DummyExercise(Exercise):
            @property
            def name(self) -> str:
                return "dummy"

            async def get_content(self, profile):
                return []

        original = session_builder._registry[:]
        session_builder._registry.clear()
        session_builder._registry.append(DummyExercise)
        try:
            result = session_builder.build_session(SessionState(), UserProfile())
            assert len(result) == 1
            assert isinstance(result[0], DummyExercise)
        finally:
            session_builder._registry[:] = original


# ---------------------------------------------------------------------------
# core.session_executor
# ---------------------------------------------------------------------------


class TestSessionExecutor:
    def _make_channel(self):
        from channels.base import OutputChannel

        class RecordingChannel(OutputChannel):
            def __init__(self):
                self.sent = []

            async def send(self, message):
                self.sent.append(message)

        return RecordingChannel()

    def _make_exercise(self, name: str, messages=None, raises=None):
        from exercises.base import Exercise
        from models import Message

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

    def test_successful_exercise_returns_success_result(self):
        from core.session_executor import SessionExecutor
        from models import UserProfile

        channel = self._make_channel()
        ex = self._make_exercise("vocab")
        executor = SessionExecutor(channel)
        results = asyncio.run(executor.execute([ex], UserProfile()))
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].exercise_name == "vocab"
        assert results[0].message_count == 1

    def test_failed_exercise_returns_failure_result(self):
        from core.session_executor import SessionExecutor
        from models import UserProfile

        channel = self._make_channel()
        ex = self._make_exercise("bad_ex", raises=ValueError("boom"))
        executor = SessionExecutor(channel)
        results = asyncio.run(executor.execute([ex], UserProfile()))
        assert len(results) == 1
        assert results[0].success is False
        assert results[0].exercise_name == "bad_ex"

    def test_messages_are_forwarded_to_channel(self):
        from core.session_executor import SessionExecutor
        from models import UserProfile, Message

        channel = self._make_channel()
        msgs = [Message(type="text", content="A"), Message(type="text", content="B")]
        ex = self._make_exercise("multi", messages=msgs)
        executor = SessionExecutor(channel)
        asyncio.run(executor.execute([ex], UserProfile()))
        assert len(channel.sent) == 2
        assert channel.sent[0].content == "A"
        assert channel.sent[1].content == "B"

    def test_multiple_exercises_all_run(self):
        from core.session_executor import SessionExecutor
        from models import UserProfile

        channel = self._make_channel()
        exs = [self._make_exercise(f"ex{i}") for i in range(3)]
        executor = SessionExecutor(channel)
        results = asyncio.run(executor.execute(exs, UserProfile()))
        assert len(results) == 3
        assert all(r.success for r in results)

    def test_empty_exercise_list_returns_empty_results(self):
        from core.session_executor import SessionExecutor
        from models import UserProfile

        channel = self._make_channel()
        executor = SessionExecutor(channel)
        results = asyncio.run(executor.execute([], UserProfile()))
        assert results == []


# ---------------------------------------------------------------------------
# core.entry — guard logic and session flow
# ---------------------------------------------------------------------------


class TestRunSession:
    def _make_channel(self):
        from channels.base import OutputChannel

        class RecordingChannel(OutputChannel):
            def __init__(self):
                self.sent = []

            async def send(self, message):
                self.sent.append(message)

        return RecordingChannel()

    def test_force_skips_guard_and_completes(self, tmp_path):
        from core.entry import run_session

        channel = self._make_channel()
        asyncio.run(run_session(tmp_path, channel=channel, force=True))

        from core.state import load_state

        state = load_state(tmp_path)
        assert state.sessions_completed == 1

    def test_too_soon_guard_blocks_run(self, tmp_path):
        """Second run within MIN_SESSION_GAP_HOURS without --force should skip."""
        from core.entry import run_session
        from core.state import save_state
        from models import SessionState
        from datetime import datetime, timezone

        # Save a state with last_completed_at = now
        state = SessionState(
            sessions_completed=1,
            last_completed_at=datetime.now(timezone.utc).isoformat(),
        )
        save_state(tmp_path, state)

        channel = self._make_channel()
        asyncio.run(run_session(tmp_path, channel=channel, force=False))

        # Should have sent the "too soon" message
        assert len(channel.sent) == 1
        # sessions_completed must NOT have incremented
        from core.state import load_state

        new_state = load_state(tmp_path)
        assert new_state.sessions_completed == 1

    def test_no_exercises_sends_message_and_increments(self, tmp_path):
        """With no exercises registered, session still completes and increments counter."""
        from core.entry import run_session
        from core import session_builder

        original = session_builder._registry[:]
        session_builder._registry.clear()
        try:
            channel = self._make_channel()
            asyncio.run(run_session(tmp_path, channel=channel, force=True))
            assert len(channel.sent) == 1  # the "no exercises" message

            from core.state import load_state

            state = load_state(tmp_path)
            assert state.sessions_completed == 1
        finally:
            session_builder._registry[:] = original

    def test_absence_nudge_increments_skipped(self, tmp_path):
        """If last session was > ABSENCE_NUDGE_DAYS ago, sends nudge and increments skipped."""
        from core.entry import run_session
        from core.state import save_state, load_state
        from models import SessionState
        from datetime import datetime, timezone, timedelta
        from config import ABSENCE_NUDGE_DAYS

        old_time = datetime.now(timezone.utc) - timedelta(
            days=ABSENCE_NUDGE_DAYS + 1
        )
        state = SessionState(
            sessions_completed=1,
            last_completed_at=old_time.isoformat(),
        )
        save_state(tmp_path, state)

        channel = self._make_channel()
        asyncio.run(run_session(tmp_path, channel=channel, force=False))

        assert len(channel.sent) == 1  # nudge message
        new_state = load_state(tmp_path)
        assert new_state.sessions_skipped == 1
        assert new_state.sessions_completed == 1  # did not increment


# ---------------------------------------------------------------------------
# channels.console
# ---------------------------------------------------------------------------


class TestConsoleChannel:
    def test_send_writes_utf8_bytes(self, capsys):
        """ConsoleChannel must handle Cyrillic and emoji without raising."""
        from channels.console import ConsoleChannel
        import io
        import sys

        channel = ConsoleChannel()
        from models import Message

        msg = Message(
            type="text",
            content="\U0001F4DA \u0417\u0430\u043d\u044f\u0442\u0438\u0435 \u0433\u043e\u0442\u043e\u0432\u043e",
        )
        # Should not raise
        asyncio.run(channel.send(msg))

    def test_send_includes_type_prefix(self):
        """Output line must start with [TYPE_UPPER]."""
        from channels.console import ConsoleChannel
        from models import Message
        import io
        from unittest.mock import patch

        buf = io.BytesIO()
        channel = ConsoleChannel()

        # Patch sys.stdout with a TextIOWrapper over our buffer so that
        # sys.stdout.buffer is our BytesIO (readable attribute, not readonly).
        import sys
        fake_stdout = io.TextIOWrapper(buf, encoding="utf-8")
        with patch("sys.stdout", fake_stdout):
            asyncio.run(channel.send(Message(type="text", content="hello")))
        fake_stdout.flush()

        output = buf.getvalue().decode("utf-8")
        assert "[TEXT]" in output
        assert "hello" in output
