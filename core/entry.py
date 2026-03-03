from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from models import Message, ExerciseCompletion, ExecutionState
from channels.base import OutputChannel
from channels.skill_channel import SkillChannel
from config import ABSENCE_NUDGE_DAYS, PROFILE_REFRESH_INTERVAL, set_data_path
from core.state_util import load_state, save_state, load_profile, save_profile
from core.session_builder import build_session
from core.session_executor import SessionExecutor, ExerciseResult

logger = logging.getLogger(__name__)


def _build_execution_state(
    exercises: list,
    results: list[ExerciseResult],
) -> ExecutionState:
    """Build an ExecutionState snapshot from a session interrupted by a
    waiting-for-user exercise.  Crashed (skipped) exercises are included in
    incomplete_names alongside exercises that never ran."""
    succeeded_names = {r.exercise_name for r in results if r.success}
    completed_count = len(succeeded_names)
    last_result = results[-1]
    run_result = last_result.data
    incomplete_names = [e.name for e in exercises if e.name not in succeeded_names]
    return ExecutionState(
        completed_count=completed_count,
        remaining_count=len(exercises) - completed_count,
        incomplete_names=incomplete_names,
        current_exercise_name=last_result.exercise_name,
        current_reason=run_result.reason if run_result else None,
        current_stage=run_result.stage if run_result else None,
        current_waiting_for_user=run_result.waiting_for_user if run_result else False,
    )



async def _check_long_absence(
    days_since: float, data_path: Path, state, channel: OutputChannel
) -> bool:
    """Send an absence nudge, record the skip, and signal done. Returns True if session should stop."""
    if days_since < ABSENCE_NUDGE_DAYS:
        return False
    await channel.send(
        Message(
            type="text",
            content=(
                "👋 Давно не занимались! "
                "Когда будешь готов — напиши, и мы продолжим."
            ),
        )
    )
    state.sessions_skipped += 1
    save_state(data_path, state)
    await channel.done(status="ok")
    return True


def _was_interrupted(results: list[ExerciseResult]) -> bool:
    """True if the session was interrupted by an exercise waiting for user input."""
    if not results:
        return False
    last = results[-1]
    return not last.success and last.data is not None and last.data.waiting_for_user


def _log_skipped_exercises(results: list[ExerciseResult], interrupted: bool) -> None:
    """Log exercises that crashed and were skipped during the session."""
    for r in results:
        if r.success:
            continue
        # The interrupting (waiting) exercise is paused, not skipped.
        if interrupted and r is results[-1]:
            continue
        logger.error(
            "Exercise '%s' crashed and was skipped. reason=%s",
            r.exercise_name,
            r.data.reason if r.data else "exception",
        )


async def _notify_no_exercises(exercises: list, channel: OutputChannel) -> None:
    """Send an empty-session message if no exercises are registered."""
    if exercises:
        return
    logger.info("No exercises registered. Session is empty.")
    await channel.send(
        Message(
            type="text",
            content=(
                "📚 Занятие готово, "
                "но упражнений пока нет. "
                "Скоро добавим!"
            ),
        )
    )


async def run_session(
    data_path: Path,
    channel: OutputChannel | None = None,
    force: bool = False,
) -> None:
    if channel is None:
        channel = SkillChannel()
        
    set_data_path(data_path)
    state = load_state(data_path)
    profile = load_profile(data_path)
    now = datetime.now(timezone.utc)

    # Clear stale execution state from a previous session that was waiting
    # for user input.  A push (run_session) always starts fresh.
    if state.execution is not None:
        logger.info(
            "Clearing stale execution state (exercise='%s', waiting=%s).",
            state.execution.current_exercise_name,
            state.execution.current_waiting_for_user,
        )
        state.execution = None
        save_state(data_path, state)

    # Guard checks (skip if --force)
    if not force and state.last_completed_at:
        last = datetime.fromisoformat(state.last_completed_at)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = now - last
        if await _check_long_absence(elapsed.total_seconds() / 86400, data_path, state, channel):
            return

    # Build and execute session
    exercises = build_session(state, profile)

    await _notify_no_exercises(exercises, channel)

    try:
        executor = SessionExecutor(channel)
        results = await executor.execute(exercises, profile)

        for result in results:
            if result.success:
                state.exercise_completions.append(
                    ExerciseCompletion(
                        exercise_name=result.exercise_name,
                        completed_at=now.isoformat(),
                    )
                )

        interrupted = _was_interrupted(results)

        if interrupted:
            state.execution = _build_execution_state(exercises, results)
        else:
            state.execution = None
            state.sessions_completed += 1
            state.last_completed_at = now.isoformat()

        save_state(data_path, state)

        _log_skipped_exercises(results, interrupted)

        if interrupted:
            logger.info(
                "Session paused at '%s' (%d/%d completed). reason=%s waiting=%s",
                state.execution.current_exercise_name,
                state.execution.completed_count,
                len(exercises),
                state.execution.current_reason,
                state.execution.current_waiting_for_user,
            )
        else:
            if PROFILE_REFRESH_INTERVAL > 0 and state.sessions_completed % PROFILE_REFRESH_INTERVAL == 0:
                logger.info(
                    "Profile refresh due (every %d sessions) -- not yet implemented.",
                    PROFILE_REFRESH_INTERVAL,
                )
            logger.info(
                "Session #%d completed. %d/%d exercises succeeded, %d skipped.",
                state.sessions_completed,
                sum(1 for r in results if r.success),
                len(exercises),
                sum(1 for r in results if not r.success),
            )

        await channel.done(status="ok")
    except Exception:
        logger.error("Session failed", exc_info=True)
        try:
            await channel.done(status="error", error="internal_error")
        except Exception:
            logger.warning("Failed to send done signal", exc_info=True)
        raise
