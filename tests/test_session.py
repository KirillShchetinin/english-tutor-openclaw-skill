"""
Tests for session flow: builder, executor, entry, and console channel.

Run from the english-tutor directory:
    python -m pytest tests/test_session.py -v
"""
from __future__ import annotations

import asyncio
import io
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from models import Message, SessionState, UserProfile, ExecutionState
from channels.base import OutputChannel
from exercises.base import Exercise, RunResult
from exercises.registry import _registry, override_registry
from core.session_executor import SessionExecutor
from core.entry import run_session
from core.state_util import load_state, save_state
from config import ABSENCE_NUDGE_DAYS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class RecordingChannel(OutputChannel):
    def __init__(self):
        self.sent: list[Message] = []
        self.done_statuses: list[str] = []

    async def send(self, message: Message) -> None:
        self.sent.append(message)

    async def done(self, status: str = "ok", **_kwargs) -> None:
        self.done_statuses.append(status)


def _make_exercise(name: str, messages=None, raises=None):
    if messages is None:
        messages = [Message(type="text", content="hello")]

    class E(Exercise):
        @property
        def name(self_):
            return name

        async def run(self_, channel, profile):
            if raises:
                raise raises
            for msg in messages:
                await channel.send(msg)
            return RunResult(completed=True)

    return E()


class _SucceedingExercise(Exercise):
    @property
    def name(self):
        return "succeeding_ex"

    async def run(self, channel, profile):
        await channel.send(Message(type="text", content="hello"))
        return RunResult(completed=True)


@contextmanager
def _registry_override(classes: list):
    original = _registry[:]
    override_registry(classes)
    try:
        yield
    finally:
        override_registry(original)


# ---------------------------------------------------------------------------
# core.session_builder
# ---------------------------------------------------------------------------


class TestBuildSession:
    def test_build_session(self):
        """Empty registry returns []; registered exercise is instantiated."""
        from core import session_builder

        with _registry_override([]):
            assert session_builder.build_session(SessionState(), UserProfile()) == []

            class DummyExercise(Exercise):
                @property
                def name(self):
                    return "dummy"

                async def run(self, channel, profile):
                    return RunResult(completed=True)

            override_registry([DummyExercise])
            result = session_builder.build_session(SessionState(), UserProfile())
            assert len(result) == 1
            assert isinstance(result[0], DummyExercise)


# ---------------------------------------------------------------------------
# exercises.registry — idempotent registration
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_register_exercise_is_idempotent(self):
        """Registering the same class twice must leave it in the registry exactly once."""
        from exercises.registry import register_exercise, get_registry, override_registry

        class OneOffExercise(Exercise):
            @property
            def name(self):
                return "one_off"

            async def run(self, channel, profile):
                return RunResult(completed=True)

        original = get_registry()
        try:
            override_registry([])
            register_exercise(OneOffExercise)
            register_exercise(OneOffExercise)  # second call — must be a no-op
            registry = get_registry()
            assert registry.count(OneOffExercise) == 1
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

    def test_stops_after_first_failure(self):
        """Given [success, fail, success], only the first two exercises run;
        the third is never reached (its message never appears in the channel)."""
        channel = RecordingChannel()

        ex_a = _make_exercise("ex_a", messages=[Message(type="text", content="from_a")])

        class FailingExercise(Exercise):
            @property
            def name(self):
                return "ex_b"

            async def run(self, ch, profile):
                await ch.send(Message(type="text", content="from_b"))
                raise RuntimeError("ex_b exploded")

        ex_b = FailingExercise()
        ex_c = _make_exercise("ex_c", messages=[Message(type="text", content="from_c")])

        results = asyncio.run(SessionExecutor(channel).execute([ex_a, ex_b, ex_c], UserProfile()))

        # Only two results — executor stopped after ex_b failed
        assert len(results) == 2
        assert results[0].exercise_name == "ex_a"
        assert results[0].success is True
        assert results[1].exercise_name == "ex_b"
        assert results[1].success is False

        # ex_c's message was never sent
        sent_contents = [m.content for m in channel.sent]
        assert "from_c" not in sent_contents

    def test_stops_on_soft_failure(self):
        """Exercise returning RunResult(completed=False) causes executor to stop;
        result has success=False and data.reason equals the RunResult reason."""
        channel = RecordingChannel()

        class SoftFailExercise(Exercise):
            @property
            def name(self):
                return "soft_fail_ex"

            async def run(self, ch, profile):
                return RunResult(completed=False, reason="no words")

        ex = SoftFailExercise()
        results = asyncio.run(SessionExecutor(channel).execute([ex], UserProfile()))

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].exercise_name == "soft_fail_ex"
        assert results[0].data is not None
        assert results[0].data.reason == "no words"


# ---------------------------------------------------------------------------
# core.entry — guard logic and session flow
# ---------------------------------------------------------------------------


class TestRunSession:
    def test_force_skips_guard_and_completes(self, tmp_path):
        channel = RecordingChannel()
        asyncio.run(run_session(tmp_path, channel=channel, force=True))
        assert load_state(tmp_path).sessions_completed == 1

    def test_no_exercises_sends_message_and_increments(self, tmp_path):
        """With no exercises registered, session still completes and increments counter."""
        channel = RecordingChannel()
        with _registry_override([]):
            asyncio.run(run_session(tmp_path, channel=channel, force=True))
        assert len(channel.sent) == 1
        assert load_state(tmp_path).sessions_completed == 1

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
# core.entry — execution state persistence on early stop / full completion
# ---------------------------------------------------------------------------


class TestRunSessionExecutionState:
    def test_incomplete_session_saves_execution_state(self, tmp_path):
        """When an exercise fails, run_session saves ExecutionState and does NOT
        increment sessions_completed."""
        class IncompleteExercise(Exercise):
            @property
            def name(self):
                return "incomplete_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, reason="waiting", waiting_for_user=True)

        channel = RecordingChannel()
        with _registry_override([IncompleteExercise, _SucceedingExercise]):
            asyncio.run(run_session(tmp_path, channel=channel, force=True))

        state = load_state(tmp_path)

        # sessions_completed must NOT be incremented
        assert state.sessions_completed == 0

        # execution snapshot must be present
        assert state.execution is not None
        exec_state = state.execution

        # incomplete_ex ran and failed; succeeding_ex was never started
        assert exec_state.completed_count == 0
        assert exec_state.remaining_count == 2   # incomplete_ex + succeeding_ex both didn't complete
        assert exec_state.current_exercise_name == "incomplete_ex"
        assert "incomplete_ex" in exec_state.incomplete_names
        assert "succeeding_ex" in exec_state.incomplete_names

    def test_stale_execution_cleared_before_new_session(self, tmp_path):
        """When run_session starts and state already has an execution snapshot
        (e.g. from a previous session waiting for user input), the stale
        execution is cleared before the new session runs."""
        stale_execution = ExecutionState(
            completed_count=0,
            remaining_count=1,
            incomplete_names=["old_interactive_ex"],
            current_exercise_name="old_interactive_ex",
            current_reason="waiting",
            current_stage=None,
            current_waiting_for_user=True,
        )
        save_state(tmp_path, SessionState(
            sessions_completed=2,
            execution=stale_execution,
        ))

        channel = RecordingChannel()
        with _registry_override([_SucceedingExercise]):
            asyncio.run(run_session(tmp_path, channel=channel, force=True))

        state = load_state(tmp_path)

        # Stale execution cleared, new session completed normally
        assert state.execution is None
        assert state.sessions_completed == 3  # incremented from 2

    def test_complete_session_clears_execution_state(self, tmp_path):
        """When all exercises succeed, run_session clears execution and increments
        sessions_completed, even if there was a pre-existing execution snapshot."""
        from exercises.registry import _registry, override_registry

        # Pre-seed state with a non-None execution
        pre_existing_execution = ExecutionState(
            completed_count=0,
            remaining_count=1,
            incomplete_names=["old_ex"],
            current_exercise_name="old_ex",
            current_reason="leftover",
            current_stage=None,
            current_waiting_for_user=False,
        )
        save_state(tmp_path, SessionState(
            sessions_completed=3,
            execution=pre_existing_execution,
        ))

        channel = RecordingChannel()
        with _registry_override([_SucceedingExercise]):
            asyncio.run(run_session(tmp_path, channel=channel, force=True))

        state = load_state(tmp_path)

        assert state.execution is None
        assert state.sessions_completed == 4   # incremented from 3


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


# ---------------------------------------------------------------------------
# core.session_executor — retry behavior
# ---------------------------------------------------------------------------


class TestSessionExecutorRetry:
    def test_retries_on_exception_and_succeeds(self):
        """An exercise that raises on the first attempt but succeeds on the retry
        should return success=True. EXERCISE_RETRY_ATTEMPTS=1 gives 2 total attempts."""
        call_count = 0

        class FlakyExercise(Exercise):
            @property
            def name(self):
                return "flaky"

            async def run(self, channel, profile):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("transient error")
                await channel.send(Message(type="text", content="recovered"))
                return RunResult(completed=True)

        channel = RecordingChannel()
        results = asyncio.run(
            SessionExecutor(channel).execute([FlakyExercise()], UserProfile())
        )

        assert call_count == 2, "exercise must be called twice (original + 1 retry)"
        assert results[0].success is True
        assert len(channel.sent) == 1
        assert channel.sent[0].content == "recovered"

    def test_exhausted_retries_returns_failure(self):
        """An exercise that raises on every attempt (original + all retries) must
        ultimately return success=False with no data (hard failure path)."""
        call_count = 0

        class AlwaysRaisesExercise(Exercise):
            @property
            def name(self):
                return "always_fails"

            async def run(self, channel, profile):
                nonlocal call_count
                call_count += 1
                raise RuntimeError("permanent failure")

        channel = RecordingChannel()
        results = asyncio.run(
            SessionExecutor(channel).execute([AlwaysRaisesExercise()], UserProfile())
        )

        # 1 original attempt + 1 retry = 2 (EXERCISE_RETRY_ATTEMPTS = 1)
        assert call_count == 2
        assert results[0].success is False
        # Hard failure (exception path) stores no RunResult data
        assert results[0].data is None


# ---------------------------------------------------------------------------
# core.entry — execution state shape for mid-session failure
# ---------------------------------------------------------------------------


class TestBuildExecutionStateMidSession:
    def test_mid_session_failure_has_correct_counts_and_names(self, tmp_path):
        """When the second of three exercises fails, completed_count=1,
        remaining_count=2, and incomplete_names contains the failed exercise plus
        the unstarted one."""

        class AlwaysSucceeds(Exercise):
            @property
            def name(self):
                return "ex_first"

            async def run(self, channel, profile):
                await channel.send(Message(type="text", content="ok"))
                return RunResult(completed=True)

        class AlwaysFails(Exercise):
            @property
            def name(self):
                return "ex_second"

            async def run(self, channel, profile):
                return RunResult(completed=False, reason="mid fail")

        class NeverRan(Exercise):
            @property
            def name(self):
                return "ex_third"

            async def run(self, channel, profile):
                return RunResult(completed=True)

        channel = RecordingChannel()
        with _registry_override([AlwaysSucceeds, AlwaysFails, NeverRan]):
            asyncio.run(run_session(tmp_path, channel=channel, force=True))

        state = load_state(tmp_path)

        assert state.sessions_completed == 0
        assert state.execution is not None
        exec_state = state.execution
        assert exec_state.completed_count == 1
        assert exec_state.remaining_count == 2
        assert exec_state.current_exercise_name == "ex_second"
        assert exec_state.current_reason == "mid fail"
        assert "ex_second" in exec_state.incomplete_names
        assert "ex_third" in exec_state.incomplete_names
        assert "ex_first" not in exec_state.incomplete_names


# ---------------------------------------------------------------------------
# core.entry — naive-timestamp handling
# ---------------------------------------------------------------------------


class TestNaiveTimestamp:
    def test_naive_timestamp_in_state_does_not_raise(self, tmp_path):
        """A last_completed_at stored without timezone info (naive ISO string) must
        be handled gracefully — not raise TypeError on comparison."""
        # Store a naive ISO timestamp (no +00:00 suffix)
        naive_ts = datetime.now(timezone.utc).replace(tzinfo=None)
        save_state(tmp_path, SessionState(
            sessions_completed=1,
            last_completed_at=naive_ts.isoformat(),
        ))

        channel = RecordingChannel()
        with _registry_override([]):
            # This would raise TypeError if entry.py did not handle the naive case
            asyncio.run(run_session(tmp_path, channel=channel, force=False))

        # Either guard triggered or session completed — no exception is the assertion
        state = load_state(tmp_path)
        assert state.sessions_completed >= 1


# ---------------------------------------------------------------------------
# core.entry — exception path emits error done signal
# ---------------------------------------------------------------------------


class TestRunSessionExceptionPath:
    def test_unexpected_exception_emits_error_done(self, tmp_path):
        """When an unhandled exception escapes executor.execute(), run_session
        calls channel.done(status='error') and then re-raises."""
        class BombExercise(Exercise):
            @property
            def name(self):
                return "bomb"

            async def run(self, channel, profile):
                raise RuntimeError("unexpected bomb")

        channel = RecordingChannel()
        # With EXERCISE_RETRY_ATTEMPTS=1 the executor retries once, then returns
        # failure; run_session itself does NOT re-raise for exercise failures.
        # To hit the outer except we need the executor itself to crash — patch it.
        with _registry_override([BombExercise]):
            with patch(
                "core.entry.SessionExecutor.execute",
                side_effect=RuntimeError("executor exploded"),
            ):
                import pytest
                with pytest.raises(RuntimeError, match="executor exploded"):
                    asyncio.run(run_session(tmp_path, channel=channel, force=True))

        assert "error" in channel.done_statuses


# ---------------------------------------------------------------------------
# core.entry — exercise_completions are persisted after successful session
# ---------------------------------------------------------------------------


class TestExerciseCompletionPersistence:
    def test_successful_exercises_are_recorded_in_state(self, tmp_path):
        """After a successful session, exercise_completions in persisted state
        should contain one entry per exercise with correct name and a timestamp."""
        channel = RecordingChannel()
        with _registry_override([_SucceedingExercise]):
            asyncio.run(run_session(tmp_path, channel=channel, force=True))

        state = load_state(tmp_path)
        assert len(state.exercise_completions) == 1
        ec = state.exercise_completions[0]
        assert ec.exercise_name == "succeeding_ex"
        # completed_at must be a parseable ISO datetime
        parsed = datetime.fromisoformat(ec.completed_at)
        assert parsed.tzinfo is not None  # must be timezone-aware

    def test_failed_exercises_are_not_recorded(self, tmp_path):
        """An exercise that fails must NOT produce an ExerciseCompletion entry."""
        class FailsExercise(Exercise):
            @property
            def name(self):
                return "fails_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, reason="nope")

        channel = RecordingChannel()
        with _registry_override([FailsExercise]):
            asyncio.run(run_session(tmp_path, channel=channel, force=True))

        state = load_state(tmp_path)
        assert state.exercise_completions == []
