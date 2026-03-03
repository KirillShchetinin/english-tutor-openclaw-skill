from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from models import Message
from channels.base import OutputChannel
from channels.skill_channel import SkillChannel
from config import ABSENCE_NUDGE_DAYS, set_data_path, reset_data_path
from messages import ABSENCE_NUDGE, NO_EXERCISES
from core.state_util import load_state, save_state, load_profile
from core.session_builder import build_session
from core.session_executor import SessionExecutor
from core.session_helpers import record_and_finalize, log_session_result

logger = logging.getLogger(__name__)


async def _check_long_absence(
    days_since: float, data_path: Path, state, channel: OutputChannel
) -> bool:
    """Send an absence nudge, record the skip, and signal done. Returns True if session should stop."""
    if days_since < ABSENCE_NUDGE_DAYS:
        return False
    await channel.send(
        Message(
            type="text",
            content=ABSENCE_NUDGE,
        )
    )
    state.sessions_skipped += 1
    save_state(data_path, state)
    return True


async def _notify_no_exercises(exercises: list, channel: OutputChannel) -> None:
    """Send an empty-session message if no exercises are registered."""
    if exercises:
        return
    logger.info("No exercises registered. Session is empty.")
    await channel.send(
        Message(
            type="text",
            content=NO_EXERCISES,
        )
    )


async def run_session(
    data_path: Path,
    channel: OutputChannel | None = None,
    force: bool = False,
) -> None:
    if channel is None:
        channel = SkillChannel()

    done_status = "ok"
    done_error: str | None = None
    try:
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

        executor = SessionExecutor(channel)
        results = await executor.execute(exercises, profile)

        record_and_finalize(state, exercises, results, now)
        save_state(data_path, state)
        log_session_result(state, exercises, results)

        if state.execution is not None and state.execution.current_waiting_for_user:
            done_status = "reply"

    except Exception:
        logger.error("Session failed", exc_info=True)
        done_status = "error"
        done_error = "internal_error"
        raise
    finally:
        try:
            kwargs: dict = {"status": done_status}
            if done_error is not None:
                kwargs["error"] = done_error
            await channel.done(**kwargs)
        except Exception:
            logger.warning("Failed to send done signal", exc_info=True)
        reset_data_path()
