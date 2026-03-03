from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from models import ExerciseCompletion, ExecutionState
from channels.base import OutputChannel
from core.session_executor import ExerciseResult
from config import SESSION_PUSH_TIMES, RESUME_CLOSE_TO_NEXT_MINUTES, PROFILE_REFRESH_INTERVAL

logger = logging.getLogger(__name__)


def _was_interrupted(results: list[ExerciseResult]) -> bool:
    """True if the session was interrupted by an exercise waiting for user input."""
    if not results:
        return False
    last = results[-1]
    return not last.success and last.data is not None and last.data.waiting_for_user


def build_execution_state(
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
        current_ask_id=run_result.ask_id if run_result else None,
    )


def record_and_finalize(
    state,
    exercises: list,
    results: list[ExerciseResult],
    now: datetime,
    *,
    pause_on_any_failure: bool = False,
) -> None:
    """Record successful completions and update session state after execution.

    Mutates *state* in place: appends exercise completions, updates
    execution/sessions_completed/last_completed_at.  Does NOT save to disk.

    When *pause_on_any_failure* is False (default, used by run_session), only
    a waiting-for-user exercise triggers execution-state preservation; crashed
    exercises are skipped and the session still completes.  When True (used by
    resume_session), any last-exercise failure preserves execution state.
    """
    for result in results:
        if result.success:
            state.exercise_completions.append(
                ExerciseCompletion(
                    exercise_name=result.exercise_name,
                    completed_at=now.isoformat(),
                )
            )

    if pause_on_any_failure:
        should_pause = bool(results) and not results[-1].success
    else:
        should_pause = _was_interrupted(results)

    if should_pause:
        state.execution = build_execution_state(exercises, results)
    else:
        state.execution = None
        state.sessions_completed += 1
        state.last_completed_at = now.isoformat()


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


def log_session_result(state, exercises: list, results: list[ExerciseResult], prefix: str = "") -> None:
    """Log session completion or pause, including skipped exercises."""
    interrupted = _was_interrupted(results)
    _log_skipped_exercises(results, interrupted)

    if state.execution is None:
        if PROFILE_REFRESH_INTERVAL > 0 and state.sessions_completed % PROFILE_REFRESH_INTERVAL == 0:
            logger.info(
                "Profile refresh due (every %d sessions) -- not yet implemented.",
                PROFILE_REFRESH_INTERVAL,
            )
        logger.info(
            "%sSession #%d completed. %d/%d exercises succeeded, %d skipped.",
            prefix,
            state.sessions_completed,
            sum(1 for r in results if r.success),
            len(exercises),
            sum(1 for r in results if not r.success),
        )
    else:
        logger.info(
            "%sSession paused at '%s' (%d/%d completed). reason=%s waiting=%s",
            prefix,
            state.execution.current_exercise_name,
            state.execution.completed_count,
            len(exercises),
            state.execution.current_reason,
            state.execution.current_waiting_for_user,
        )


def minutes_to_next_lesson(now: datetime) -> float | None:
    """Return minutes until the next SESSION_PUSH_TIMES slot, or None if no push times."""
    if not SESSION_PUSH_TIMES:
        return None
    today = now.date()
    candidates = []
    for time_str in SESSION_PUSH_TIMES:
        h, m = map(int, time_str.split(":"))
        slot_dt = datetime(today.year, today.month, today.day, h, m, tzinfo=timezone.utc)
        if slot_dt > now:
            candidates.append(slot_dt)
    if not candidates:
        h, m = map(int, SESSION_PUSH_TIMES[0].split(":"))
        tomorrow = today + timedelta(days=1)
        next_lesson = datetime(tomorrow.year, tomorrow.month, tomorrow.day, h, m, tzinfo=timezone.utc)
        return (next_lesson - now).total_seconds() / 60
    next_lesson = min(candidates)
    return (next_lesson - now).total_seconds() / 60
