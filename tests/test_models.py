"""
Tests for models (dataclass serialization) and state persistence.

Run from the english-tutor directory:
    python -m pytest tests/test_models.py -v
"""
from __future__ import annotations

import pytest

from models import Message, ExerciseCompletion, SessionState, UserProfile
from core.state import load_state, save_state, load_profile, save_profile


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


class TestMessage:
    def test_to_dict_parse_mode_handling(self):
        """parse_mode appears in dict only when set to a non-None value."""
        plain = Message(type="text", content="Hello")
        assert plain.to_dict() == {"type": "text", "content": "Hello"}

        explicit_none = Message(type="text", content="url", parse_mode=None)
        assert "parse_mode" not in explicit_none.to_dict()

        markdown = Message(type="text", content="**bold**", parse_mode="Markdown")
        assert markdown.to_dict()["parse_mode"] == "Markdown"


# ---------------------------------------------------------------------------
# SessionState (includes ExerciseCompletion round-trip)
# ---------------------------------------------------------------------------


class TestSessionState:
    def test_round_trip(self):
        """Full round-trip preserves all fields including nested completions."""
        ec = ExerciseCompletion(
            exercise_name="vocab_drill",
            completed_at="2026-02-24T05:00:00+00:00",
        )
        state = SessionState(
            sessions_completed=7,
            last_completed_at="2026-02-24T05:00:00+00:00",
            sessions_skipped=2,
            exercise_completions=[ec],
        )
        restored = SessionState.from_dict(state.to_dict())

        assert restored.sessions_completed == 7
        assert restored.last_completed_at == "2026-02-24T05:00:00+00:00"
        assert restored.sessions_skipped == 2
        assert len(restored.exercise_completions) == 1
        assert restored.exercise_completions[0].exercise_name == "vocab_drill"
        assert restored.exercise_completions[0].completed_at == "2026-02-24T05:00:00+00:00"

    def test_from_dict_defaults_on_empty(self):
        state = SessionState.from_dict({})
        assert state.sessions_completed == 0
        assert state.last_completed_at is None
        assert state.sessions_skipped == 0
        assert state.exercise_completions == []


# ---------------------------------------------------------------------------
# UserProfile
# ---------------------------------------------------------------------------


class TestUserProfile:
    def test_round_trip(self):
        profile = UserProfile(
            summary="Advanced speaker",
            words_learned=150,
            words_in_progress=30,
            accuracy=0.87,
            streak=14,
            weak_spots=["articles", "prepositions"],
            strong_topics=["past tense", "vocabulary"],
        )
        restored = UserProfile.from_dict(profile.to_dict())

        assert restored.summary == "Advanced speaker"
        assert restored.words_learned == 150
        assert restored.words_in_progress == 30
        assert abs(restored.accuracy - 0.87) < 1e-9
        assert restored.streak == 14
        assert restored.weak_spots == ["articles", "prepositions"]
        assert restored.strong_topics == ["past tense", "vocabulary"]

    def test_from_dict_defaults_on_empty(self):
        profile = UserProfile.from_dict({})
        assert profile.summary == ""
        assert profile.words_learned == 0
        assert profile.accuracy == 0.0
        assert profile.weak_spots == []

    def test_to_dict_returns_independent_copy(self):
        """Mutating the to_dict output must not affect the stored profile."""
        profile = UserProfile(weak_spots=["articles"])
        d = profile.to_dict()
        d["weak_spots"].append("prepositions")
        assert profile.weak_spots == ["articles"]


# ---------------------------------------------------------------------------
# State & profile persistence
# ---------------------------------------------------------------------------


class TestStatePersistence:
    def test_missing_files_return_defaults(self, tmp_path):
        """Both load_state and load_profile return defaults when files don't exist."""
        state = load_state(tmp_path)
        assert state.sessions_completed == 0

        profile = load_profile(tmp_path)
        assert profile.summary == ""
        assert profile.words_learned == 0

    def test_round_trip(self, tmp_path):
        """save + load preserves data; save creates nested directories."""
        nested = tmp_path / "a" / "b"

        save_state(nested, SessionState(
            sessions_completed=3,
            last_completed_at="2026-02-24T05:00:00+00:00",
            sessions_skipped=1,
            exercise_completions=[
                ExerciseCompletion("drill", "2026-02-24T05:00:00+00:00"),
            ],
        ))
        restored_state = load_state(nested)
        assert restored_state.sessions_completed == 3
        assert restored_state.last_completed_at == "2026-02-24T05:00:00+00:00"
        assert len(restored_state.exercise_completions) == 1

        save_profile(nested, UserProfile(summary="Test", words_learned=42))
        restored_profile = load_profile(nested)
        assert restored_profile.summary == "Test"
        assert restored_profile.words_learned == 42

    def test_corrupted_json_raises(self, tmp_path):
        """Corrupted JSON in both state and profile files raises RuntimeError."""
        (tmp_path / "session_state.json").write_text("{bad json: [}", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Corrupted state file"):
            load_state(tmp_path)

        (tmp_path / "user_profile.json").write_text("not-json!!!", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Corrupted profile file"):
            load_profile(tmp_path)
