from __future__ import annotations

import logging
from dataclasses import dataclass

from models import UserProfile
from exercises.base import Exercise
from channels.base import OutputChannel
from config import EXERCISE_RETRY_ATTEMPTS

logger = logging.getLogger(__name__)


@dataclass
class ExerciseResult:
    exercise_name: str
    success: bool
    message_count: int = 0


class SessionExecutor:
    def __init__(self, channel: OutputChannel) -> None:
        self._channel = channel

    async def execute(
        self, exercises: list[Exercise], profile: UserProfile
    ) -> list[ExerciseResult]:
        results = []
        for exercise in exercises:
            result = await self._run_exercise(exercise, profile)
            results.append(result)
        return results

    async def _run_exercise(
        self, exercise: Exercise, profile: UserProfile
    ) -> ExerciseResult:
        """Run single exercise with retry on failure."""
        attempts = 1 + EXERCISE_RETRY_ATTEMPTS  # 1 original + retries
        for attempt in range(attempts):
            try:
                messages = await exercise.get_content(profile)
                for msg in messages:
                    await self._channel.send(msg)
                return ExerciseResult(
                    exercise_name=exercise.name,
                    success=True,
                    message_count=len(messages),
                )
            except Exception:
                if attempt < attempts - 1:
                    logger.warning(
                        "Exercise '%s' failed (attempt %d), retrying...",
                        exercise.name,
                        attempt + 1,
                        exc_info=True,
                    )
                else:
                    logger.error(
                        "Exercise '%s' failed after %d attempts, skipping.",
                        exercise.name,
                        attempts,
                        exc_info=True,
                    )
        return ExerciseResult(exercise_name=exercise.name, success=False)
