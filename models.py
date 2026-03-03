from __future__ import annotations

from dataclasses import dataclass, field


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
