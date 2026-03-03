"""
Tests for resume_session and build_exercises_by_names.

Run from the english-tutor directory:
    python -m pytest tests/test_resume.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from models import Message, SessionState, ExecutionState
from exercises.base import Exercise, InteractiveExercise, RunResult
from core.resume import resume_session
from core.session_builder import build_exercises_by_names
from core.state_util import load_state, save_state
from config import RESUME_CLOSE_TO_NEXT_MINUTES
from tests.helpers import RecordingChannel, registry_override as _registry_override


def _make_execution_state(
    exercise_name: str,
    waiting_for_user: bool = True,
    incomplete_names: list[str] | None = None,
    stage: tuple[int, int] | None = None,
    reason: str | None = None,
) -> ExecutionState:
    """Helper to build an ExecutionState for resume tests."""
    if incomplete_names is None:
        incomplete_names = [exercise_name]
    return ExecutionState(
        completed_count=0,
        remaining_count=len(incomplete_names),
        incomplete_names=incomplete_names,
        current_exercise_name=exercise_name,
        current_reason=reason,
        current_stage=stage,
        current_waiting_for_user=waiting_for_user,
    )


# ---------------------------------------------------------------------------
# core.session_builder -- build_exercises_by_names
# ---------------------------------------------------------------------------


class TestBuildExercisesByNames:
    def test_returns_exercises_in_requested_order(self):
        """Exercises are returned in the order of the names list, not registry order."""
        class ExA(Exercise):
            @property
            def name(self):
                return "ex_a"

            async def run(self, channel, profile):
                return RunResult(completed=True)

        class ExB(Exercise):
            @property
            def name(self):
                return "ex_b"

            async def run(self, channel, profile):
                return RunResult(completed=True)

        with _registry_override([ExA, ExB]):
            result = build_exercises_by_names(["ex_b", "ex_a"])

        assert len(result) == 2
        assert result[0].name == "ex_b"
        assert result[1].name == "ex_a"

    def test_skips_unknown_names(self):
        """Names not in the registry are silently ignored."""
        class ExA(Exercise):
            @property
            def name(self):
                return "ex_a"

            async def run(self, channel, profile):
                return RunResult(completed=True)

        with _registry_override([ExA]):
            result = build_exercises_by_names(["ex_a", "ghost_exercise", "another_missing"])

        assert len(result) == 1
        assert result[0].name == "ex_a"

    def test_returns_empty_for_all_unknown_names(self):
        """When every name is unknown, an empty list is returned."""
        class ExA(Exercise):
            @property
            def name(self):
                return "ex_a"

            async def run(self, channel, profile):
                return RunResult(completed=True)

        with _registry_override([ExA]):
            result = build_exercises_by_names(["no_such_exercise"])

        assert result == []

    def test_returns_empty_for_empty_names_list(self):
        """An empty names list produces an empty result regardless of registry."""
        class ExA(Exercise):
            @property
            def name(self):
                return "ex_a"

            async def run(self, channel, profile):
                return RunResult(completed=True)

        with _registry_override([ExA]):
            result = build_exercises_by_names([])

        assert result == []


# ---------------------------------------------------------------------------
# core.entry -- resume_session
# ---------------------------------------------------------------------------


class TestResumeSession:
    # ------------------------------------------------------------------
    # Guard tests
    # ------------------------------------------------------------------

    def test_no_execution_state_sends_message_and_done_ok(self, tmp_path):
        """If state.execution is None, sends 'no unfinished session' message and done(ok)."""
        # State has no execution -- default SessionState
        save_state(tmp_path, SessionState())

        channel = RecordingChannel()
        asyncio.run(resume_session(tmp_path, user_input="hello", channel=channel))

        assert len(channel.sent) == 1
        assert "незавершённого" in channel.sent[0].content
        assert channel.done_statuses == ["ok"]
        # State must be untouched
        state = load_state(tmp_path)
        assert state.execution is None
        assert state.sessions_completed == 0

    def test_not_waiting_for_user_sends_error_clears_execution_and_saves(self, tmp_path):
        """If execution.current_waiting_for_user is False, sends error message,
        clears execution, and persists the cleared state."""
        exec_state = _make_execution_state("some_ex", waiting_for_user=False)
        save_state(tmp_path, SessionState(execution=exec_state))

        channel = RecordingChannel()
        asyncio.run(resume_session(tmp_path, user_input="hi", channel=channel))

        assert len(channel.sent) == 1
        assert "ошибки" in channel.sent[0].content
        assert channel.done_statuses == ["ok"]
        state = load_state(tmp_path)
        assert state.execution is None

    def test_exercise_not_in_registry_sends_unavailable_clears_execution(self, tmp_path):
        """If the current_exercise_name is not in the registry, sends 'unavailable'
        message, clears execution, and saves."""
        exec_state = _make_execution_state("nonexistent_exercise", waiting_for_user=True)
        save_state(tmp_path, SessionState(execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([]):  # empty registry -- exercise cannot be found
            asyncio.run(resume_session(tmp_path, user_input="answer", channel=channel))

        assert len(channel.sent) == 1
        assert "недоступно" in channel.sent[0].content
        assert channel.done_statuses == ["ok"]
        state = load_state(tmp_path)
        assert state.execution is None

    def test_close_to_next_session_sends_wait_message_preserves_execution(self, tmp_path):
        """If next push is within RESUME_CLOSE_TO_NEXT_MINUTES, sends 'new session
        coming' message and does NOT clear execution state."""

        class InteractiveEx(InteractiveExercise):
            @property
            def name(self):
                return "interactive_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True)

            async def reply(self, user_input, channel, profile):
                return RunResult(completed=True)

        exec_state = _make_execution_state("interactive_ex", waiting_for_user=True)
        save_state(tmp_path, SessionState(execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([InteractiveEx]):
            # Patch _minutes_to_next_push to return a value within the threshold
            with patch(
                "core.resume.minutes_to_next_lesson",
                return_value=float(RESUME_CLOSE_TO_NEXT_MINUTES) - 1,
            ):
                asyncio.run(resume_session(tmp_path, user_input="answer", channel=channel))

        assert len(channel.sent) == 1
        assert "занятие" in channel.sent[0].content.lower()
        assert channel.done_statuses == ["ok"]
        # Execution preserved -- user will resume in the next session
        state = load_state(tmp_path)
        assert state.execution is not None
        assert state.execution.current_exercise_name == "interactive_ex"

    # ------------------------------------------------------------------
    # Reply behavior tests
    # ------------------------------------------------------------------

    def test_reply_completes_exercise_no_remaining_increments_sessions(self, tmp_path):
        """When reply returns completed=True and no remaining exercises, the session
        completes: sessions_completed is incremented and execution is cleared."""

        class InteractiveEx(InteractiveExercise):
            @property
            def name(self):
                return "interactive_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True)

            async def reply(self, user_input, channel, profile):
                await channel.send(Message(type="text", content="Правильно!"))
                return RunResult(completed=True)

        exec_state = _make_execution_state(
            "interactive_ex",
            waiting_for_user=True,
            incomplete_names=["interactive_ex"],
        )
        save_state(tmp_path, SessionState(sessions_completed=2, execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([InteractiveEx]):
            asyncio.run(resume_session(tmp_path, user_input="my answer", channel=channel))

        state = load_state(tmp_path)
        assert state.execution is None
        assert state.sessions_completed == 3
        assert channel.done_statuses == ["ok"]
        # The reply message must have been forwarded
        assert any("Правильно" in m.content for m in channel.sent)
        # ExerciseCompletion must be recorded
        assert any(ec.exercise_name == "interactive_ex" for ec in state.exercise_completions)

    def test_reply_completes_then_remaining_exercises_run_to_completion(self, tmp_path):
        """When reply completes the current exercise and there are remaining exercises,
        the executor runs them; if all succeed the session completes fully."""

        class InteractiveEx(InteractiveExercise):
            @property
            def name(self):
                return "interactive_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True)

            async def reply(self, user_input, channel, profile):
                return RunResult(completed=True)

        class FollowUpEx(Exercise):
            @property
            def name(self):
                return "followup_ex"

            async def run(self, channel, profile):
                await channel.send(Message(type="text", content="follow up done"))
                return RunResult(completed=True)

        exec_state = _make_execution_state(
            "interactive_ex",
            waiting_for_user=True,
            incomplete_names=["interactive_ex", "followup_ex"],
        )
        save_state(tmp_path, SessionState(sessions_completed=0, execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([InteractiveEx, FollowUpEx]):
            asyncio.run(resume_session(tmp_path, user_input="my answer", channel=channel))

        state = load_state(tmp_path)
        assert state.execution is None
        assert state.sessions_completed == 1
        assert channel.done_statuses == ["ok"]
        assert any(m.content == "follow up done" for m in channel.sent)
        names = [ec.exercise_name for ec in state.exercise_completions]
        assert "interactive_ex" in names
        assert "followup_ex" in names

    def test_reply_still_waiting_updates_stage_does_not_clear_execution(self, tmp_path):
        """When reply returns completed=False, waiting_for_user=True, the execution
        state is updated with the new stage but NOT cleared; sessions_completed
        stays the same."""
        new_stage = (2, 3)

        class MultiTurnEx(InteractiveExercise):
            @property
            def name(self):
                return "multiturn_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True, stage=(1, 3))

            async def reply(self, user_input, channel, profile):
                await channel.send(Message(type="text", content="Next clue"))
                return RunResult(
                    completed=False,
                    waiting_for_user=True,
                    stage=new_stage,
                    reason="awaiting next answer",
                )

        exec_state = _make_execution_state(
            "multiturn_ex",
            waiting_for_user=True,
            stage=(1, 3),
        )
        save_state(tmp_path, SessionState(sessions_completed=1, execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([MultiTurnEx]):
            asyncio.run(resume_session(tmp_path, user_input="partial answer", channel=channel))

        state = load_state(tmp_path)
        assert state.sessions_completed == 1           # unchanged
        assert state.execution is not None             # not cleared
        assert state.execution.current_stage == new_stage
        assert state.execution.current_reason == "awaiting next answer"
        assert state.execution.current_waiting_for_user is True
        assert channel.done_statuses == ["reply"]

    def test_reply_gives_up_sets_waiting_false_does_not_clear(self, tmp_path):
        """When reply returns completed=False, waiting_for_user=False, execution is
        updated with current_waiting_for_user=False so the next resume guard fires."""

        class GivesUpEx(InteractiveExercise):
            @property
            def name(self):
                return "givesup_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True)

            async def reply(self, user_input, channel, profile):
                await channel.send(Message(type="text", content="Too many wrong answers."))
                return RunResult(
                    completed=False,
                    waiting_for_user=False,
                    reason="max_attempts",
                )

        exec_state = _make_execution_state("givesup_ex", waiting_for_user=True)
        save_state(tmp_path, SessionState(execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([GivesUpEx]):
            asyncio.run(resume_session(tmp_path, user_input="wrong", channel=channel))

        state = load_state(tmp_path)
        assert state.execution is not None
        assert state.execution.current_waiting_for_user is False
        assert state.execution.current_reason == "max_attempts"
        assert state.sessions_completed == 0
        assert channel.done_statuses == ["ok"]

    def test_remaining_exercises_fail_after_reply_saves_new_execution_state(self, tmp_path):
        """When reply succeeds but a subsequent exercise fails, a new ExecutionState
        is built from the remaining exercises rather than clearing it."""

        class InteractiveEx(InteractiveExercise):
            @property
            def name(self):
                return "interactive_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True)

            async def reply(self, user_input, channel, profile):
                return RunResult(completed=True)

        class FailingFollowUp(Exercise):
            @property
            def name(self):
                return "failing_followup"

            async def run(self, channel, profile):
                return RunResult(completed=False, reason="data unavailable")

        exec_state = _make_execution_state(
            "interactive_ex",
            waiting_for_user=True,
            incomplete_names=["interactive_ex", "failing_followup"],
        )
        save_state(tmp_path, SessionState(execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([InteractiveEx, FailingFollowUp]):
            asyncio.run(resume_session(tmp_path, user_input="answer", channel=channel))

        state = load_state(tmp_path)
        # Session did not complete
        assert state.sessions_completed == 0
        # A new execution state was built pointing at the failing follow-up
        assert state.execution is not None
        assert state.execution.current_exercise_name == "failing_followup"
        assert state.execution.current_reason == "data unavailable"
        assert channel.done_statuses == ["ok"]


# ---------------------------------------------------------------------------
# ask_id mismatch guard and hard-crash-on-reply behavior
# ---------------------------------------------------------------------------


def _make_execution_state_with_ask_id(
    exercise_name: str,
    ask_id: str | None = None,
    waiting_for_user: bool = True,
    incomplete_names: list[str] | None = None,
) -> ExecutionState:
    """Helper to build an ExecutionState that includes current_ask_id."""
    if incomplete_names is None:
        incomplete_names = [exercise_name]
    return ExecutionState(
        completed_count=0,
        remaining_count=len(incomplete_names),
        incomplete_names=incomplete_names,
        current_exercise_name=exercise_name,
        current_reason=None,
        current_stage=None,
        current_waiting_for_user=waiting_for_user,
        current_ask_id=ask_id,
    )


class TestAskIdGuard:
    """Tests for ask_id mismatch guard and hard-crash-on-reply behavior."""

    # ------------------------------------------------------------------
    # ask_id mismatch — current skipped, remaining run
    # ------------------------------------------------------------------

    def test_ask_id_mismatch_skips_current_and_runs_remaining(self, tmp_path):
        """When caller's ask_id doesn't match stored ask_id, the current
        (interactive) exercise is skipped and remaining exercises still run.
        The session completes if remaining exercises succeed."""

        class InteractiveEx(InteractiveExercise):
            reply_called = False

            @property
            def name(self):
                return "interactive_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True)

            async def reply(self, user_input, channel, profile):
                InteractiveEx.reply_called = True
                return RunResult(completed=True)

        class FollowUpEx(Exercise):
            @property
            def name(self):
                return "followup_ex"

            async def run(self, channel, profile):
                await channel.send(Message(type="text", content="followup ran"))
                return RunResult(completed=True)

        exec_state = _make_execution_state_with_ask_id(
            exercise_name="interactive_ex",
            ask_id="stored-token-111",
            incomplete_names=["interactive_ex", "followup_ex"],
        )
        save_state(tmp_path, SessionState(sessions_completed=0, execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([InteractiveEx, FollowUpEx]):
            asyncio.run(
                resume_session(
                    tmp_path,
                    user_input="my answer",
                    ask_id="different-token-999",
                    channel=channel,
                )
            )

        # reply() must NOT have been called — exercise was skipped
        assert not InteractiveEx.reply_called
        # Remaining exercise must have run
        assert any(m.content == "followup ran" for m in channel.sent)
        # Session must complete
        state = load_state(tmp_path)
        assert state.sessions_completed == 1
        assert state.execution is None
        assert channel.done_statuses == ["ok"]

    def test_ask_id_mismatch_no_remaining_still_completes(self, tmp_path):
        """When ask_id mismatches and there are no remaining exercises, the
        session completes cleanly (does not hang or error out)."""

        class InteractiveEx(InteractiveExercise):
            @property
            def name(self):
                return "interactive_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True)

            async def reply(self, user_input, channel, profile):
                return RunResult(completed=True)

        exec_state = _make_execution_state_with_ask_id(
            exercise_name="interactive_ex",
            ask_id="stored-token",
            incomplete_names=["interactive_ex"],
        )
        save_state(tmp_path, SessionState(sessions_completed=0, execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([InteractiveEx]):
            asyncio.run(
                resume_session(
                    tmp_path,
                    user_input="my answer",
                    ask_id="wrong-token",
                    channel=channel,
                )
            )

        state = load_state(tmp_path)
        assert state.sessions_completed == 1
        assert state.execution is None
        assert channel.done_statuses == ["ok"]

    # ------------------------------------------------------------------
    # ask_id match — reply proceeds normally
    # ------------------------------------------------------------------

    def test_ask_id_match_reply_proceeds(self, tmp_path):
        """When caller's ask_id matches stored ask_id, the reply is accepted
        and the exercise runs to completion."""

        class InteractiveEx(InteractiveExercise):
            reply_called = False

            @property
            def name(self):
                return "interactive_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True)

            async def reply(self, user_input, channel, profile):
                InteractiveEx.reply_called = True
                await channel.send(Message(type="text", content="correct!"))
                return RunResult(completed=True)

        exec_state = _make_execution_state_with_ask_id(
            exercise_name="interactive_ex",
            ask_id="matching-token",
            incomplete_names=["interactive_ex"],
        )
        save_state(tmp_path, SessionState(sessions_completed=0, execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([InteractiveEx]):
            asyncio.run(
                resume_session(
                    tmp_path,
                    user_input="correct answer",
                    ask_id="matching-token",
                    channel=channel,
                )
            )

        assert InteractiveEx.reply_called
        assert any(m.content == "correct!" for m in channel.sent)
        state = load_state(tmp_path)
        assert state.sessions_completed == 1
        assert state.execution is None
        assert channel.done_statuses == ["ok"]

    # ------------------------------------------------------------------
    # ask_id=None from caller — always accepted
    # ------------------------------------------------------------------

    def test_caller_ask_id_none_always_accepted_even_with_stored_ask_id(self, tmp_path):
        """When caller passes ask_id=None, the reply is always accepted
        regardless of what ask_id is stored."""

        class InteractiveEx(InteractiveExercise):
            reply_called = False

            @property
            def name(self):
                return "interactive_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True)

            async def reply(self, user_input, channel, profile):
                InteractiveEx.reply_called = True
                return RunResult(completed=True)

        exec_state = _make_execution_state_with_ask_id(
            exercise_name="interactive_ex",
            ask_id="some-stored-token",
            incomplete_names=["interactive_ex"],
        )
        save_state(tmp_path, SessionState(sessions_completed=0, execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([InteractiveEx]):
            asyncio.run(
                resume_session(
                    tmp_path,
                    user_input="my answer",
                    ask_id=None,  # caller sends no ask_id
                    channel=channel,
                )
            )

        # reply() must have been called — no mismatch when caller sends None
        assert InteractiveEx.reply_called
        state = load_state(tmp_path)
        assert state.sessions_completed == 1
        assert state.execution is None
        assert channel.done_statuses == ["ok"]

    # ------------------------------------------------------------------
    # stored ask_id=None — caller's ask_id always accepted
    # ------------------------------------------------------------------

    def test_stored_ask_id_none_any_caller_ask_id_accepted(self, tmp_path):
        """When stored ask_id is None, no mismatch is possible — any value
        the caller sends is accepted and the reply proceeds."""

        class InteractiveEx(InteractiveExercise):
            reply_called = False

            @property
            def name(self):
                return "interactive_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True)

            async def reply(self, user_input, channel, profile):
                InteractiveEx.reply_called = True
                return RunResult(completed=True)

        exec_state = _make_execution_state_with_ask_id(
            exercise_name="interactive_ex",
            ask_id=None,  # stored ask_id is absent
            incomplete_names=["interactive_ex"],
        )
        save_state(tmp_path, SessionState(sessions_completed=0, execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([InteractiveEx]):
            asyncio.run(
                resume_session(
                    tmp_path,
                    user_input="my answer",
                    ask_id="caller-provides-some-token",
                    channel=channel,
                )
            )

        assert InteractiveEx.reply_called
        state = load_state(tmp_path)
        assert state.sessions_completed == 1
        assert state.execution is None
        assert channel.done_statuses == ["ok"]

    # ------------------------------------------------------------------
    # Hard crash on reply — remaining exercises still run
    # ------------------------------------------------------------------

    def test_hard_crash_on_reply_skips_current_runs_remaining(self, tmp_path):
        """When reply() raises an exception on every retry attempt
        (data=None after exhausting retries), the current exercise is
        skipped and remaining exercises still run to completion."""

        class CrashingEx(InteractiveExercise):
            @property
            def name(self):
                return "crashing_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True)

            async def reply(self, user_input, channel, profile):
                raise RuntimeError("simulated hard crash")

        class FollowUpEx(Exercise):
            @property
            def name(self):
                return "followup_ex"

            async def run(self, channel, profile):
                await channel.send(Message(type="text", content="tail ran"))
                return RunResult(completed=True)

        exec_state = _make_execution_state_with_ask_id(
            exercise_name="crashing_ex",
            incomplete_names=["crashing_ex", "followup_ex"],
        )
        save_state(tmp_path, SessionState(sessions_completed=0, execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([CrashingEx, FollowUpEx]):
            asyncio.run(
                resume_session(
                    tmp_path,
                    user_input="my answer",
                    channel=channel,
                )
            )

        # Remaining exercise must have run despite the crash
        assert any(m.content == "tail ran" for m in channel.sent)
        # Session must complete (crashing exercise is skipped, tail succeeded)
        state = load_state(tmp_path)
        assert state.sessions_completed == 1
        assert state.execution is None
        assert channel.done_statuses == ["ok"]

    def test_hard_crash_on_reply_no_remaining_session_completes(self, tmp_path):
        """When reply() hard-crashes and there are no remaining exercises,
        the session completes without hanging or erroring."""

        class CrashingEx(InteractiveExercise):
            @property
            def name(self):
                return "crashing_ex"

            async def run(self, channel, profile):
                return RunResult(completed=False, waiting_for_user=True)

            async def reply(self, user_input, channel, profile):
                raise RuntimeError("simulated hard crash on every attempt")

        exec_state = _make_execution_state_with_ask_id(
            exercise_name="crashing_ex",
            incomplete_names=["crashing_ex"],
        )
        save_state(tmp_path, SessionState(sessions_completed=2, execution=exec_state))

        channel = RecordingChannel()
        with _registry_override([CrashingEx]):
            asyncio.run(
                resume_session(
                    tmp_path,
                    user_input="my answer",
                    channel=channel,
                )
            )

        state = load_state(tmp_path)
        # Session completes: the only exercise crashed so it's treated as
        # skipped; remaining list is empty, so record_and_finalize sees
        # all_results=[] which is not a failure → completes.
        assert state.sessions_completed == 3
        assert state.execution is None
        assert channel.done_statuses == ["ok"]
