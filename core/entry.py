from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from models import Message, ExerciseCompletion
from channels.base import OutputChannel
from channels.telegram import TelegramChannel
from config import MIN_SESSION_GAP_HOURS, ABSENCE_NUDGE_DAYS, PROFILE_REFRESH_INTERVAL, set_data_path
from core.state import load_state, save_state, load_profile, save_profile
from core.session_builder import build_session
from core.session_executor import SessionExecutor
import exercises.vocab  # noqa: F401 — triggers @register_exercise

logger = logging.getLogger(__name__)


async def run_session(
    data_path: Path,
    channel: OutputChannel | None = None,
    force: bool = False,
) -> None:
    if channel is None:
        channel = TelegramChannel()
    set_data_path(data_path)
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
                            "⏳ Слишком рано для нового занятия. "
                            "Отдохни немного, скоро продолжим!"
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
                            "👋 Давно не занимались! "
                            "Когда будешь готов — напиши, и мы продолжим."
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
                    "📚 Занятие готово, "
                    "но упражнений пока нет. "
                    "Скоро добавим!"
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
