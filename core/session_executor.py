from __future__ import annotations

import logging
from dataclasses import dataclass

from models import UserProfile
from exercises.base import Exercise, RunResult
from channels.base import OutputChannel
from config import EXERCISE_RETRY_ATTEMPTS

logger = logging.getLogger(__name__)


@dataclass
class ExerciseResult:
    exercise_name: str
    success: bool
    data: RunResult | None = None  # set on incomplete runs to record progress


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
            if not result.success:
                if result.data and result.data.waiting_for_user:
                    break  # interactive exercise — interrupt session for resume
                logger.error(
                    "Skipping crashed exercise '%s', continuing session.",
                    exercise.name,
                )
        return results

    async def _run_exercise(
        self, exercise: Exercise, profile: UserProfile
    ) -> ExerciseResult:
        """Run single exercise with retry on unexpected failure."""
        attempts = 1 + EXERCISE_RETRY_ATTEMPTS  # 1 original + retries
        for attempt in range(attempts):
            try:
                run_result = await exercise.run(self._channel, profile)
                if run_result.completed:
                    return ExerciseResult(exercise_name=exercise.name, success=True)
                # Soft failure: exercise decided it can't complete — respect it, no retry.
                logger.warning(
                    "Exercise '%s' did not complete: %s",
                    exercise.name,
                    run_result.reason,
                )
                return ExerciseResult(
                    exercise_name=exercise.name, success=False, data=run_result
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
