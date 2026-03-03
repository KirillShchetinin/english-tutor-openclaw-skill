from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from models import Message
from channels.base import OutputChannel
from channels.skill_channel import SkillChannel
from config import RESUME_CLOSE_TO_NEXT_MINUTES, set_data_path, reset_data_path
from messages import (
    NO_PENDING_SESSION,
    SESSION_ERROR,
    CLOSE_TO_NEXT_SESSION,
    EXERCISE_UNAVAILABLE,
)
from core.state_util import load_state, save_state, load_profile
from core.session_builder import build_exercises_by_names
from core.session_executor import SessionExecutor
from exercises.base import InteractiveExercise
from core.session_helpers import (
    minutes_to_next_lesson,
    record_and_finalize,
    log_session_result,
)

logger = logging.getLogger(__name__)


async def resume_session(
    data_path: Path,
    user_input: str,
    ask_id: str | None = None,
    channel: OutputChannel | None = None,
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

        # --- guards -------------------------------------------------------

        if state.execution is None or state.execution.current_exercise_name is None:
            await channel.send(
                Message(type="text", content=NO_PENDING_SESSION)
            )
            if state.execution is not None:
                state.execution = None
                save_state(data_path, state)
            return

        if not state.execution.current_waiting_for_user:
            await channel.send(
                Message(type="text", content=SESSION_ERROR)
            )
            state.execution = None
            save_state(data_path, state)
            return

        # --- close-to-next-session guard ----------------------------------

        mins = minutes_to_next_lesson(now)
        if mins is not None and mins < RESUME_CLOSE_TO_NEXT_MINUTES:
            await channel.send(
                Message(type="text", content=CLOSE_TO_NEXT_SESSION)
            )
            return

        # --- resolve exercises --------------------------------------------

        all_names = state.execution.incomplete_names
        exercises = build_exercises_by_names(all_names)

        if not exercises:
            await channel.send(
                Message(type="text", content=EXERCISE_UNAVAILABLE)
            )
            state.execution = None
            save_state(data_path, state)
            return

        current = exercises[0]
        remaining = exercises[1:]
        run_current = True

        # --- ask_id mismatch guard ----------------------------------------
        stored_ask_id = state.execution.current_ask_id
        if ask_id is not None and stored_ask_id is not None and ask_id != stored_ask_id:
            logger.info(
                "ask_id mismatch (got=%s, stored=%s); skipping exercise '%s'.",
                ask_id,
                stored_ask_id,
                current.name,
            )
            exercises = remaining
            # skipping current exercise if we can't match correctness of questions.
            run_current = False
            state.execution = None
            try:
                save_state(data_path, state)
            except Exception:
                logger.warning("Failed to save state after ask_id mismatch", exc_info=True)


        # --- execute ------------------------------------------------------

        executor = SessionExecutor(channel)

        current_succeeded = False
        run_remaining = not run_current  # ask_id mismatch → skip current, run rest
        all_results = []

        if run_current and not isinstance(current, InteractiveExercise):
            logger.error(
                "Expected InteractiveExercise for resume but got %s (%s); skipping",
                type(current).__name__,
                current.name,
            )
            run_remaining = True
        elif run_current:
            reply_result = await executor.reply_exercise(current, user_input, profile)
            current_succeeded = reply_result.success
            if not current_succeeded and reply_result.data is None:
                # Hard crash (all retries exhausted) — skip and move on.
                logger.error("Reply exercise hard-failed for %s; skipping", current.name)
                run_remaining = True
            else:
                all_results = [reply_result]
                # This is interactive interrupt case - we need reply from user.
                run_remaining = current_succeeded

        if remaining and run_remaining:
            tail_results = await executor.execute(remaining, profile)
            all_results.extend(tail_results)

        record_and_finalize(state, exercises, all_results, now, pause_on_any_failure=True)
        save_state(data_path, state)
        log_session_result(state, exercises, all_results, prefix="Resumed: ")

        if state.execution is not None and state.execution.current_waiting_for_user:
            done_status = "reply"

    except Exception:
        logger.error("Resume session failed", exc_info=True)
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
