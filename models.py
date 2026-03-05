from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class Message:
    type: str
    content: str
    parse_mode: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"type": self.type, "content": self.content}
        if self.parse_mode is not None:
            d["parse_mode"] = self.parse_mode
        return d


@dataclass
class ExerciseCompletion:
    exercise_name: str
    completed_at: str

    def to_dict(self) -> dict:
        return {
            "exercise_name": self.exercise_name,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ExerciseCompletion:
        return cls(
            exercise_name=data["exercise_name"],
            completed_at=data["completed_at"],
        )


@dataclass
class ExecutionState:
    """Snapshot of a session that stopped before all exercises completed."""
    completed_count: int
    remaining_count: int
    incomplete_names: list[str]          # all exercises that didn't finish
    current_exercise_name: str | None    # the one that was running when stopped
    current_reason: str | None           # RunResult.reason
    current_stage: tuple[int, int] | None  # RunResult.stage, e.g. (3, 5)
    current_waiting_for_user: bool       # RunResult.waiting_for_user
    current_ask_id: str | None = None    # token from the question message

    def to_dict(self) -> dict:
        d = {
            "completed_count": self.completed_count,
            "remaining_count": self.remaining_count,
            "incomplete_names": self.incomplete_names,
            "current_exercise_name": self.current_exercise_name,
            "current_reason": self.current_reason,
            "current_stage": list(self.current_stage) if self.current_stage is not None else None,
            "current_waiting_for_user": self.current_waiting_for_user,
        }
        d["current_ask_id"] = self.current_ask_id
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ExecutionState:
        raw_stage = data.get("current_stage")
        return cls(
            completed_count=data["completed_count"],
            remaining_count=data["remaining_count"],
            incomplete_names=data.get("incomplete_names", []),
            current_exercise_name=data.get("current_exercise_name"),
            current_reason=data.get("current_reason"),
            current_stage=tuple(raw_stage) if raw_stage is not None else None,
            current_waiting_for_user=data.get("current_waiting_for_user", False),
            current_ask_id=data.get("current_ask_id"),
        )


@dataclass
class SessionState:
    sessions_completed: int = 0
    last_completed_at: str | None = None
    sessions_skipped: int = 0
    exercise_completions: list[ExerciseCompletion] = field(default_factory=list)
    execution: ExecutionState | None = None

    def to_dict(self) -> dict:
        return {
            "sessions_completed": self.sessions_completed,
            "last_completed_at": self.last_completed_at,
            "sessions_skipped": self.sessions_skipped,
            "exercise_completions": [
                ec.to_dict() for ec in self.exercise_completions
            ],
            "execution": self.execution.to_dict() if self.execution else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SessionState:
        raw_exec = data.get("execution")
        return cls(
            sessions_completed=data.get("sessions_completed", 0),
            last_completed_at=data.get("last_completed_at"),
            sessions_skipped=data.get("sessions_skipped", 0),
            exercise_completions=[
                ExerciseCompletion.from_dict(ec)
                for ec in data.get("exercise_completions", [])
            ],
            execution=ExecutionState.from_dict(raw_exec) if raw_exec else None,
        )


@dataclass
class UserProfile:
    summary: str = ""
    words_learned: int = 0
    words_in_progress: int = 0
    accuracy: float = 0.0
    streak: int = 0
    weak_spots: list[str] = field(default_factory=list)
    strong_topics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "words_learned": self.words_learned,
            "words_in_progress": self.words_in_progress,
            "accuracy": self.accuracy,
            "streak": self.streak,
            "weak_spots": list(self.weak_spots),
            "strong_topics": list(self.strong_topics),
        }

    @classmethod
    def from_dict(cls, data: dict) -> UserProfile:
        return cls(
            summary=data.get("summary", ""),
            words_learned=data.get("words_learned", 0),
            words_in_progress=data.get("words_in_progress", 0),
            accuracy=data.get("accuracy", 0.0),
            streak=data.get("streak", 0),
            weak_spots=list(data.get("weak_spots", [])),
            strong_topics=list(data.get("strong_topics", [])),
        )


@functools.total_ordering
@dataclass(frozen=True)
class StudentLevel:
    """CEFR level with sublevel (e.g. A2-3). 30 ordinal positions total."""

    CEFR_BANDS: ClassVar[list[str]] = ["A1", "A2", "B1", "B2", "C1", "C2"]

    cefr: str
    sublevel: int

    @classmethod
    def parse(cls, s: str) -> StudentLevel:
        """Parse 'A2-3' or bare 'A2' (defaults sublevel to 1)."""
        parts = s.split("-", 1)
        cefr = parts[0]
        if cefr not in cls.CEFR_BANDS:
            raise ValueError(
                f"Unknown CEFR band '{cefr}' — "
                f"expected one of {cls.CEFR_BANDS}"
            )
        if len(parts) == 2:
            try:
                sublevel = int(parts[1])
            except ValueError:
                raise ValueError(
                    f"Invalid sublevel '{parts[1]}' in '{s}' — must be an integer 1-5"
                )
        else:
            sublevel = 1
        if sublevel < 1 or sublevel > 5:
            raise ValueError(
                f"Sublevel {sublevel} out of range in '{s}' — must be 1-5"
            )
        return cls(cefr=cefr, sublevel=sublevel)

    def to_ordinal(self) -> int:
        """Flat integer 1-30 for comparison (A1-1=1 ... C2-5=30)."""
        band_index = self.CEFR_BANDS.index(self.cefr)
        return band_index * 5 + self.sublevel

    @classmethod
    def from_ordinal(cls, n: int) -> StudentLevel:
        """Inverse of to_ordinal. Raises ValueError if not in [1, 30]."""
        if n < 1 or n > 30:
            raise ValueError(f"Ordinal {n} out of range — must be 1-30")
        band_index = (n - 1) // 5
        sublevel = (n - 1) % 5 + 1
        return cls(cefr=cls.CEFR_BANDS[band_index], sublevel=sublevel)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StudentLevel):
            return NotImplemented
        return self.to_ordinal() == other.to_ordinal()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, StudentLevel):
            return NotImplemented
        return self.to_ordinal() < other.to_ordinal()

    def __hash__(self) -> int:
        return hash(self.to_ordinal())

    def difficulty_window(self) -> tuple[StudentLevel, StudentLevel]:
        """Full current CEFR band plus a 1-sublevel buffer on each side."""
        band_index = self.CEFR_BANDS.index(self.cefr)
        band_start = band_index * 5 + 1
        band_end = band_index * 5 + 5
        low = max(1, band_start - 1)
        high = min(30, band_end + 1)
        return (StudentLevel.from_ordinal(low), StudentLevel.from_ordinal(high))

    def __str__(self) -> str:
        return f"{self.cefr}-{self.sublevel}"
