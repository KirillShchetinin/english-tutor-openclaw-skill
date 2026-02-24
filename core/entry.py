from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from models import Message, ExerciseCompletion
from channels.base import OutputChannel
from channels.telegram import TelegramChannel
from config import MIN_SESSION_GAP_HOURS, ABSENCE_NUDGE_DAYS, PROFILE_REFRESH_INTERVAL
from core.state import load_state, save_state, load_profile, save_profile
from core.session_builder import build_session
from core.session_executor import SessionExecutor

logger = logging.getLogger(__name__)


async def run_session(
    data_path: Path,
    channel: OutputChannel | None = None,
    force: bool = False,
) -> None:
    if channel is None:
        channel = TelegramChannel()
    state = load_state(data_path)
    profile = load_profile(data_path)
    now = datetime.now(timezone.utc)

    # Guard checks (skip if --force)
    if not force:
        if state.last_completed_at:
            last = datetime.fromisoformat(state.last_completed_at)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            hours_since = (now - last).total_seconds() / 3600

            if hours_since < MIN_SESSION_GAP_HOURS:
                await channel.send(
                    Message(
                        type="text",
                        content=(
                            "\u23f3 \u0421\u043b\u0438\u0448\u043a\u043e\u043c \u0440\u0430\u043d\u043e \u0434\u043b\u044f \u043d\u043e\u0432\u043e\u0433\u043e \u0437\u0430\u043d\u044f\u0442\u0438\u044f. "
                            "\u041e\u0442\u0434\u043e\u0445\u043d\u0438 \u043d\u0435\u043c\u043d\u043e\u0433\u043e, \u0441\u043a\u043e\u0440\u043e \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u043c!"
                        ),
                    )
                )
                return

            days_since = (now - last).total_seconds() / 86400
            if days_since >= ABSENCE_NUDGE_DAYS:
                await channel.send(
                    Message(
                        type="text",
                        content=(
                            "\U0001F44B \u0414\u0430\u0432\u043d\u043e \u043d\u0435 \u0437\u0430\u043d\u0438\u043c\u0430\u043b\u0438\u0441\u044c! "
                            "\u041a\u043e\u0433\u0434\u0430 \u0431\u0443\u0434\u0435\u0448\u044c \u0433\u043e\u0442\u043e\u0432 \u2014 \u043d\u0430\u043f\u0438\u0448\u0438, \u0438 \u043c\u044b \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u043c."
                        ),
                    )
                )
                state.sessions_skipped += 1
                save_state(data_path, state)
                return

    # Build and execute session
    exercises = build_session(state, profile)

    if not exercises:
        logger.info("No exercises registered. Session is empty.")
        await channel.send(
            Message(
                type="text",
                content=(
                    "\U0001F4DA \u0417\u0430\u043d\u044f\u0442\u0438\u0435 \u0433\u043e\u0442\u043e\u0432\u043e, "
                    "\u043d\u043e \u0443\u043f\u0440\u0430\u0436\u043d\u0435\u043d\u0438\u0439 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442. "
                    "\u0421\u043a\u043e\u0440\u043e \u0434\u043e\u0431\u0430\u0432\u0438\u043c!"
                ),
            )
        )

    executor = SessionExecutor(channel)
    results = await executor.execute(exercises, profile)

    # Update state per-exercise for crash recovery
    for result in results:
        if result.success:
            state.exercise_completions.append(
                ExerciseCompletion(
                    exercise_name=result.exercise_name,
                    completed_at=now.isoformat(),
                )
            )
            save_state(data_path, state)

    # Mark session complete
    state.sessions_completed += 1
    state.last_completed_at = now.isoformat()
    save_state(data_path, state)

    # Profile refresh stub (every N sessions)
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
