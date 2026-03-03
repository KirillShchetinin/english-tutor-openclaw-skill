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
    """Build an ExecutionState snapshot from a stopped execution."""
    completed_count = sum(1 for r in results if r.success)
    last_result = results[-1]
    run_result = last_result.data
    # incomplete_names: the exercise that stopped + all exercises never run
    incomplete_names = [e.name for e in exercises[completed_count:]]
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

        # Record successful completions.
        # executor.execute() runs exercises serially and returns all results
        # at once — a single save_state at the end of this block is sufficient.
        for result in results:
            if result.success:
                state.exercise_completions.append(
                    ExerciseCompletion(
                        exercise_name=result.exercise_name,
                        completed_at=now.isoformat(),
                    )
                )

        # An empty exercise list counts as a completed session (no failures possible).
        all_succeeded = not results or results[-1].success
        if all_succeeded:
            state.execution = None
            state.sessions_completed += 1
            state.last_completed_at = now.isoformat()
        else:
            state.execution = _build_execution_state(exercises, results)

        save_state(data_path, state)

        if all_succeeded:
            if PROFILE_REFRESH_INTERVAL > 0 and state.sessions_completed % PROFILE_REFRESH_INTERVAL == 0:
                logger.info(
                    "Profile refresh due (every %d sessions) -- not yet implemented.",
                    PROFILE_REFRESH_INTERVAL,
                )
            logger.info(
                "Session #%d completed. %d/%d exercises succeeded.",
                state.sessions_completed,
                sum(1 for r in results if r.success),
                len(results),
            )
        else:
            logger.info(
                "Session paused at '%s' (%d/%d completed). reason=%s waiting=%s",
                state.execution.current_exercise_name,
                state.execution.completed_count,
                len(exercises),
                state.execution.current_reason,
                state.execution.current_waiting_for_user,
            )

        await channel.done(status="ok")
    except Exception:
        logger.error("Session failed", exc_info=True)
        try:
            await channel.done(status="error", error="internal_error")
        except Exception:
            logger.warning("Failed to send done signal", exc_info=True)
        raise
