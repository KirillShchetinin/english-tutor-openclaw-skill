"""
Tests for models (dataclass serialization) and state persistence.

Run from the english-tutor directory:
    python -m pytest tests/test_models.py -v
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

import json

from models import Message, ExerciseCompletion, ExecutionState, SessionState, StudentLevel, UserProfile
from core.state_util import load_state, save_state, load_profile, save_profile
from config import get_student_level, set_data_path


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

    def test_save_state_atomic_write_cleans_up_tmp_on_error(self, tmp_path):
        """If save_state's rename step fails, the .tmp file is removed and the
        exception is re-raised — no half-written tmp file is left behind."""
        state = SessionState(sessions_completed=1)
        tmp_file = tmp_path / "session_state.tmp"

        with patch("pathlib.Path.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                save_state(tmp_path, state)

        assert not tmp_file.exists()



# ---------------------------------------------------------------------------
# ExecutionState
# ---------------------------------------------------------------------------


class TestExecutionState:
    def test_round_trip_with_stage(self):
        """ExecutionState with a non-None stage serializes and deserializes correctly;
        stage comes back as a tuple."""
        es = ExecutionState(
            completed_count=2,
            remaining_count=1,
            incomplete_names=["ex_c", "ex_d"],
            current_exercise_name="ex_c",
            current_reason="no words available",
            current_stage=(3, 5),
            current_waiting_for_user=True,
        )
        restored = ExecutionState.from_dict(es.to_dict())

        assert restored.completed_count == 2
        assert restored.remaining_count == 1
        assert restored.incomplete_names == ["ex_c", "ex_d"]
        assert restored.current_exercise_name == "ex_c"
        assert restored.current_reason == "no words available"
        assert restored.current_stage == (3, 5)
        assert isinstance(restored.current_stage, tuple)
        assert restored.current_waiting_for_user is True

    def test_round_trip_no_stage(self):
        """stage=None round-trips as None."""
        es = ExecutionState(
            completed_count=0,
            remaining_count=3,
            incomplete_names=["ex_a", "ex_b", "ex_c"],
            current_exercise_name="ex_a",
            current_reason=None,
            current_stage=None,
            current_waiting_for_user=False,
        )
        restored = ExecutionState.from_dict(es.to_dict())

        assert restored.current_stage is None
        assert restored.current_reason is None
        assert restored.current_waiting_for_user is False

    def test_session_state_round_trip_with_execution(self):
        """A SessionState with a non-None execution round-trips through to_dict/from_dict."""
        execution = ExecutionState(
            completed_count=1,
            remaining_count=2,
            incomplete_names=["ex_b", "ex_c"],
            current_exercise_name="ex_b",
            current_reason="waiting",
            current_stage=(1, 3),
            current_waiting_for_user=True,
        )
        state = SessionState(
            sessions_completed=5,
            last_completed_at="2026-02-01T12:00:00+00:00",
            sessions_skipped=0,
            exercise_completions=[],
            execution=execution,
        )
        restored = SessionState.from_dict(state.to_dict())

        assert restored.sessions_completed == 5
        assert restored.execution is not None
        assert restored.execution.completed_count == 1
        assert restored.execution.remaining_count == 2
        assert restored.execution.incomplete_names == ["ex_b", "ex_c"]
        assert restored.execution.current_exercise_name == "ex_b"
        assert restored.execution.current_reason == "waiting"
        assert restored.execution.current_stage == (1, 3)
        assert isinstance(restored.execution.current_stage, tuple)
        assert restored.execution.current_waiting_for_user is True

    def test_session_state_round_trip_execution_none(self):
        """execution=None round-trips as None."""
        state = SessionState(
            sessions_completed=3,
            execution=None,
        )
        restored = SessionState.from_dict(state.to_dict())

        assert restored.execution is None
        assert restored.sessions_completed == 3


# ---------------------------------------------------------------------------
# StudentLevel
# ---------------------------------------------------------------------------


class TestStudentLevel:
    # --- Parsing ---

    def test_parse_full_format(self):
        """'A2-3' parses to cefr='A2', sublevel=3."""
        level = StudentLevel.parse("A2-3")
        assert level.cefr == "A2"
        assert level.sublevel == 3

    def test_parse_bare_cefr(self):
        """'A2' with no sublevel defaults to sublevel=1."""
        level = StudentLevel.parse("A2")
        assert level.cefr == "A2"
        assert level.sublevel == 1

    def test_parse_all_bands(self):
        """All six CEFR bands parse without error."""
        for band in ["A1", "A2", "B1", "B2", "C1", "C2"]:
            level = StudentLevel.parse(f"{band}-3")
            assert level.cefr == band
            assert level.sublevel == 3

    def test_parse_invalid_band_raises(self):
        """An unknown CEFR band raises ValueError."""
        with pytest.raises(ValueError, match="Unknown CEFR band"):
            StudentLevel.parse("D1-2")

    def test_parse_sublevel_out_of_range_raises(self):
        """Sublevels 0 and 6 are outside the valid range and raise ValueError."""
        with pytest.raises(ValueError, match="out of range"):
            StudentLevel.parse("A1-0")
        with pytest.raises(ValueError, match="out of range"):
            StudentLevel.parse("A1-6")

    def test_parse_empty_string_raises(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError):
            StudentLevel.parse("")

    # --- Ordinals ---

    def test_ordinal_boundaries(self):
        """A1-1 maps to ordinal 1 and C2-5 maps to ordinal 30."""
        assert StudentLevel.parse("A1-1").to_ordinal() == 1
        assert StudentLevel.parse("C2-5").to_ordinal() == 30

    def test_from_ordinal_round_trip(self):
        """from_ordinal(to_ordinal(x)) == x for every position 1-30."""
        for n in range(1, 31):
            level = StudentLevel.from_ordinal(n)
            assert level.to_ordinal() == n

    def test_from_ordinal_out_of_range_raises(self):
        """Ordinals 0 and 31 are out of range and raise ValueError."""
        with pytest.raises(ValueError, match="out of range"):
            StudentLevel.from_ordinal(0)
        with pytest.raises(ValueError, match="out of range"):
            StudentLevel.from_ordinal(31)

    # --- Comparison ---

    def test_less_than(self):
        """A1-2 is less than A1-3."""
        assert StudentLevel.parse("A1-2") < StudentLevel.parse("A1-3")

    def test_equal(self):
        """Two levels with the same band and sublevel are equal."""
        assert StudentLevel.parse("B2-4") == StudentLevel.parse("B2-4")

    def test_greater_than_across_bands(self):
        """B1-1 is greater than A2-5."""
        assert StudentLevel.parse("B1-1") > StudentLevel.parse("A2-5")

    # --- Difficulty window ---

    def test_window_mid_range(self):
        """A2-2 window: one sublevel below band start (A1-5) to one above band end (B1-1)."""
        low, high = StudentLevel.parse("A2-2").difficulty_window()
        assert low == StudentLevel.parse("A1-5")
        assert high == StudentLevel.parse("B1-1")

    def test_window_bottom_clamp(self):
        """A1-3 window: clamps at A1-1 on the low end (no band below A1)."""
        low, high = StudentLevel.parse("A1-3").difficulty_window()
        assert low == StudentLevel.parse("A1-1")
        assert high == StudentLevel.parse("A2-1")

    def test_window_top_clamp(self):
        """C2-4 window: clamps at C2-5 on the high end (no band above C2)."""
        low, high = StudentLevel.parse("C2-4").difficulty_window()
        assert low == StudentLevel.parse("C1-5")
        assert high == StudentLevel.parse("C2-5")

    # --- Str ---

    def test_str_format(self):
        """str() returns the canonical 'BAND-sublevel' format."""
        assert str(StudentLevel.parse("B2-4")) == "B2-4"


# ---------------------------------------------------------------------------
# get_student_level (config.py)
# ---------------------------------------------------------------------------


class TestGetStudentLevel:
    def test_reads_config_and_returns_level(self, tmp_path):
        """Writes config.json with student_level and verifies the returned level."""
        # conftest.py writes A1-1 by default; overwrite with a different level.
        (tmp_path / "config.json").write_text(
            json.dumps({"student_level": "B2-3"}), encoding="utf-8"
        )
        set_data_path(tmp_path)
        try:
            level = get_student_level()
        finally:
            set_data_path(None)
        assert level == StudentLevel.parse("B2-3")
        assert level.cefr == "B2"
        assert level.sublevel == 3

    def test_missing_file_raises(self, tmp_path):
        """No config.json → RuntimeError mentioning config.json."""
        (tmp_path / "config.json").unlink()
        set_data_path(tmp_path)
        try:
            with pytest.raises(RuntimeError, match="config.json"):
                get_student_level()
        finally:
            set_data_path(None)

    def test_missing_key_raises(self, tmp_path):
        """config.json without student_level key → RuntimeError."""
        (tmp_path / "config.json").write_text(
            json.dumps({"other_key": "value"}), encoding="utf-8"
        )
        set_data_path(tmp_path)
        try:
            with pytest.raises(RuntimeError, match="student_level"):
                get_student_level()
        finally:
            set_data_path(None)
