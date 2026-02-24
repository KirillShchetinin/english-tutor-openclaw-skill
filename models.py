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
class SessionState:
    sessions_completed: int = 0
    last_completed_at: str | None = None
    sessions_skipped: int = 0
    exercise_completions: list[ExerciseCompletion] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sessions_completed": self.sessions_completed,
            "last_completed_at": self.last_completed_at,
            "sessions_skipped": self.sessions_skipped,
            "exercise_completions": [
                ec.to_dict() for ec in self.exercise_completions
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> SessionState:
        return cls(
            sessions_completed=data.get("sessions_completed", 0),
            last_completed_at=data.get("last_completed_at"),
            sessions_skipped=data.get("sessions_skipped", 0),
            exercise_completions=[
                ExerciseCompletion.from_dict(ec)
                for ec in data.get("exercise_completions", [])
            ],
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
