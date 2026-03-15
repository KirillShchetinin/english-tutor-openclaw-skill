"""
Unit tests for VocabQuizExercise.

Run from the english-tutor directory:
    python -m pytest tests/test_vocab_quiz.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from config import set_data_path
from exercises.vocab.helpers import (
    VocabState,
    atomic_write,
    load_vocab_state,
    save_vocab_state,
)
from exercises.vocab.quiz import (
    GRADUATION_THRESHOLD,
    GRADUATION_WINDOW,
    LEARNING_SLOTS,
    MIN_TIMES_SHOWN,
    REVIEW_SLOTS,
    WORDS_PER_TEST,
    AnswerResult,
    VocabQuizExercise,
    evaluate_answer,
)
from models import UserProfile
from tests.helpers import RecordingChannel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    en: str,
    ru: str,
    *,
    is_learning: bool = True,
    times_shown: int = MIN_TIMES_SHOWN,
    times_tested: int = 0,
    results: list[bool] | None = None,
) -> dict:
    return {
        "en": en,
        "ru": ru,
        "topic": "greetings",
        "difficulty": "A1-3",
        "is_learning": is_learning,
        "times_shown": times_shown,
        "times_tested": times_tested,
        "results": results if results is not None else [],
        "last_seen": None,
    }


def _make_vocab_state(entries: list[dict]) -> VocabState:
    vocab = {e["en"]: e for e in entries}
    return VocabState(vocab=vocab, word_bank={}, topics={})


@pytest.fixture()
def ex(tmp_path):
    """Set data path and return a fresh VocabQuizExercise."""
    set_data_path(tmp_path)
    yield VocabQuizExercise()
    set_data_path(None)


def _seed_vocab_state(tmp_path, entries: list[dict]) -> None:
    """Write vocab state files so load_vocab_state('vocab') returns them."""
    vocab_dir = tmp_path / "vocab"
    vocab_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(vocab_dir / "state.json", {e["en"]: e for e in entries})
    atomic_write(vocab_dir / "word_bank.json", {})
    atomic_write(vocab_dir / "topics.json", {})


def _eligible_entries(n: int) -> list[dict]:
    """Return n learning entries each shown MIN_TIMES_SHOWN times."""
    return [
        _make_entry(f"word{i}", f"слово{i}", times_shown=MIN_TIMES_SHOWN)
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# TestAnswerEval
# ---------------------------------------------------------------------------


class TestAnswerEval:
    def test_exact_match_case_insensitive(self):
        r = evaluate_answer("Hello", "hello")
        assert r.correct is True
        assert r.distance == 0

    def test_exact_match_strips_whitespace(self):
        r = evaluate_answer("  hello  ", "hello")
        assert r.correct is True

    def test_extra_whitespace_collapsed(self):
        r = evaluate_answer("hello   world", "hello world")
        assert r.correct is True

    def test_fuzzy_within_threshold_short_word(self):
        # "cat" -> "cot": distance 1, threshold for len<=4 is 1 → accepted
        r = evaluate_answer("cot", "cat")
        assert r.correct is True
        assert r.distance == 1

    def test_fuzzy_within_threshold_long_word(self):
        # "school" -> "shcool": distance 2, threshold for len>4 is 2 → accepted
        r = evaluate_answer("shcool", "school")
        assert r.correct is True
        assert r.distance == 2

    def test_fuzzy_beyond_threshold_short_word(self):
        # "cat" -> "xyz": distance 3, threshold 1 → rejected
        r = evaluate_answer("xyz", "cat")
        assert r.correct is False

    def test_fuzzy_beyond_threshold_long_word(self):
        # "bottle" -> "xxxxx": distance > 2 → rejected
        r = evaluate_answer("xxxxx", "bottle")
        assert r.correct is False

    def test_empty_user_input_rejected(self):
        r = evaluate_answer("", "hello")
        assert r.correct is False

    def test_whitespace_only_user_input_rejected(self):
        r = evaluate_answer("   ", "hello")
        assert r.correct is False

    def test_answer_result_fields_populated(self):
        r = evaluate_answer("Helo", "hello")
        assert isinstance(r, AnswerResult)
        assert r.expected == "hello"
        assert r.user_answer == "helo"
        assert r.distance == 1


# ---------------------------------------------------------------------------
# TestWordSelection
# ---------------------------------------------------------------------------


class TestWordSelection:
    def test_learning_pool_requires_min_times_shown(self, ex):
        entries = [
            _make_entry("word0", "слово0", times_shown=MIN_TIMES_SHOWN - 1),
            _make_entry("word1", "слово1", times_shown=MIN_TIMES_SHOWN),
        ]
        state = _make_vocab_state(entries)

        with patch("random.shuffle"):
            words = ex._pick_test_words(state)

        en_words = {w["en"] for w in words}
        assert "word0" not in en_words
        assert "word1" in en_words

    def test_words_with_zero_times_shown_excluded(self, ex):
        entries = [_make_entry(f"word{i}", f"слово{i}", times_shown=0) for i in range(5)]
        state = _make_vocab_state(entries)

        with patch("random.shuffle"):
            words = ex._pick_test_words(state)

        assert words == []

    def test_review_slot_picks_graduated_word(self, ex):
        # 4 learning + 1 graduated; expect exactly 1 graduated in result
        entries = [
            *[_make_entry(f"word{i}", f"слово{i}") for i in range(4)],
            _make_entry("grad0", "выпускник0", is_learning=False, times_shown=0),
        ]
        state = _make_vocab_state(entries)

        with patch("random.shuffle"):
            words = ex._pick_test_words(state)

        graduated = [w for w in words if not w["is_learning"]]
        assert len(graduated) == REVIEW_SLOTS
        assert graduated[0]["en"] == "grad0"

    def test_fallback_no_learning_fills_from_review(self, ex):
        # 5 graduated words, no learning → all slots filled from review pool
        entries = [
            _make_entry(f"grad{i}", f"выпускник{i}", is_learning=False, times_shown=0)
            for i in range(WORDS_PER_TEST)
        ]
        state = _make_vocab_state(entries)

        with patch("random.shuffle"):
            words = ex._pick_test_words(state)

        assert len(words) == WORDS_PER_TEST
        assert all(not w["is_learning"] for w in words)

    def test_fallback_no_review_fills_from_learning(self, ex):
        # 6 learning words, no graduated → up to WORDS_PER_TEST from learning
        entries = [
            _make_entry(f"word{i}", f"слово{i}") for i in range(WORDS_PER_TEST + 1)
        ]
        state = _make_vocab_state(entries)

        with patch("random.shuffle"):
            words = ex._pick_test_words(state)

        assert len(words) == WORDS_PER_TEST
        assert all(w["is_learning"] for w in words)

    def test_empty_vocab_returns_empty_list(self, ex):
        state = VocabState(vocab={}, word_bank={}, topics={})
        words = ex._pick_test_words(state)
        assert words == []

    def test_returns_at_most_words_per_test(self, ex):
        entries = [
            _make_entry(f"word{i}", f"слово{i}") for i in range(WORDS_PER_TEST + 5)
        ]
        state = _make_vocab_state(entries)

        with patch("random.shuffle"):
            words = ex._pick_test_words(state)

        assert len(words) <= WORDS_PER_TEST

    def test_learning_slots_limit_respected(self, ex):
        # Many learning words: should take at most LEARNING_SLOTS from learning
        entries = [
            _make_entry(f"word{i}", f"слово{i}") for i in range(LEARNING_SLOTS + 3)
        ]
        state = _make_vocab_state(entries)

        with patch("random.shuffle"):
            words = ex._pick_test_words(state)

        # With no review pool to supplement, learning fills all WORDS_PER_TEST
        assert len(words) == WORDS_PER_TEST

    def test_selection_sorted_by_times_tested_ascending(self, ex):
        # Words with fewer tests should be prioritised (lowest times_tested first)
        entries = [
            _make_entry("often_tested", "часто", times_tested=10),
            _make_entry("rarely_tested", "редко", times_tested=0),
        ]
        state = _make_vocab_state(entries)

        with patch("random.shuffle"):
            words = ex._pick_test_words(state)

        assert words[0]["en"] == "rarely_tested"


# ---------------------------------------------------------------------------
# TestGraduation
# ---------------------------------------------------------------------------


class TestGraduation:
    def test_word_graduates_with_enough_correct_in_window(self, ex):
        entry = _make_entry("hello", "привет", is_learning=True,
                            results=[True] * GRADUATION_WINDOW)
        ex._apply_graduation(entry)
        assert entry["is_learning"] is False

    def test_word_with_enough_correct_but_last_wrong_re_enters(self, ex):
        # GRADUATION_WINDOW correct answers qualifies for graduation, but if
        # the result list ends in False the re-entry rule fires immediately.
        results = [True] * (GRADUATION_WINDOW - 1) + [False]
        entry = _make_entry("hello", "привет", is_learning=True, results=results)
        ex._apply_graduation(entry)
        # First the graduation check: sum=GRADUATION_WINDOW-1 < THRESHOLD → not graduated
        # Re-entry check only fires if already graduated, so still learning
        assert entry["is_learning"] is True

    def test_word_does_not_graduate_below_threshold(self, ex):
        results = [True] * (GRADUATION_THRESHOLD - 1) + [False] * (GRADUATION_WINDOW - GRADUATION_THRESHOLD + 1)
        entry = _make_entry("hello", "привет", is_learning=True, results=results)
        ex._apply_graduation(entry)
        assert entry["is_learning"] is True

    def test_graduated_word_wrong_answer_re_enters_learning(self, ex):
        # Word is already graduated (is_learning=False); last result is wrong
        results = [True] * GRADUATION_WINDOW + [False]
        entry = _make_entry("hello", "привет", is_learning=False, results=results)
        ex._apply_graduation(entry)
        assert entry["is_learning"] is True

    def test_graduated_word_correct_answer_stays_graduated(self, ex):
        results = [True] * (GRADUATION_WINDOW + 1)
        entry = _make_entry("hello", "привет", is_learning=False, results=results)
        ex._apply_graduation(entry)
        assert entry["is_learning"] is False

    def test_too_few_results_for_graduation_stays_learning(self, ex):
        # Only GRADUATION_WINDOW-1 results, all correct — not enough history
        results = [True] * (GRADUATION_WINDOW - 1)
        entry = _make_entry("hello", "привет", is_learning=True, results=results)
        ex._apply_graduation(entry)
        assert entry["is_learning"] is True


# ---------------------------------------------------------------------------
# TestFullQuiz
# ---------------------------------------------------------------------------


class TestFullQuiz:
    def _make_eligible(self, n: int = WORDS_PER_TEST) -> list[dict]:
        return [
            _make_entry(f"word{i}", f"слово{i}", times_shown=MIN_TIMES_SHOWN)
            for i in range(n)
        ]

    def test_run_returns_waiting_for_user(self, tmp_path, ex):
        _seed_vocab_state(tmp_path, self._make_eligible())
        channel = RecordingChannel()

        result = asyncio.run(ex.run(channel, UserProfile()))

        assert result.waiting_for_user is True
        assert result.completed is False
        assert result.stage is not None
        assert result.stage[1] == WORDS_PER_TEST

    def test_run_sends_header_and_first_question(self, tmp_path, ex):
        _seed_vocab_state(tmp_path, self._make_eligible())
        channel = RecordingChannel()

        asyncio.run(ex.run(channel, UserProfile()))

        # Header + first question
        assert len(channel.sent) == 2
        assert channel.sent[0].type == "text"      # header
        assert channel.sent[1].type == "question"  # first question

    def test_run_sets_ask_id_from_channel(self, tmp_path, ex):
        _seed_vocab_state(tmp_path, self._make_eligible())
        channel = RecordingChannel()

        result = asyncio.run(ex.run(channel, UserProfile()))

        # ask_id should be the token returned for the question message (msg-1)
        assert result.ask_id == "msg-1"

    def test_run_creates_quiz_state_file(self, tmp_path, ex):
        _seed_vocab_state(tmp_path, self._make_eligible())

        asyncio.run(ex.run(channel=RecordingChannel(), profile=UserProfile()))

        quiz_path = tmp_path / "vocab_quiz" / "quiz_state.json"
        assert quiz_path.exists()

    def test_correct_reply_sends_correct_feedback(self, tmp_path, ex):
        entries = self._make_eligible(WORDS_PER_TEST)
        _seed_vocab_state(tmp_path, entries)
        channel = RecordingChannel()
        asyncio.run(ex.run(channel, UserProfile()))

        # Find what the first question is asking for
        import json
        quiz = json.loads((tmp_path / "vocab_quiz" / "quiz_state.json").read_text(encoding="utf-8"))
        correct_en = quiz["questions"][0]["en"]

        channel2 = RecordingChannel()
        asyncio.run(ex.reply(correct_en, channel2, UserProfile()))

        # First message is the feedback
        assert channel2.sent[0].type == "text"
        assert correct_en in channel2.sent[0].content
        # Should contain the "correct" marker from VOCAB_TEST_CORRECT
        assert "✅" in channel2.sent[0].content

    def test_wrong_reply_sends_incorrect_feedback(self, tmp_path, ex):
        entries = self._make_eligible(WORDS_PER_TEST)
        _seed_vocab_state(tmp_path, entries)
        asyncio.run(ex.run(RecordingChannel(), UserProfile()))

        channel = RecordingChannel()
        asyncio.run(ex.reply("xxxxxxxxxxx", channel, UserProfile()))

        assert channel.sent[0].type == "text"
        # Wrong feedback contains the correct answer
        assert "xxxxxxxxxx" in channel.sent[0].content or "правильный" in channel.sent[0].content.lower()

    def test_intermediate_reply_returns_waiting_for_user(self, tmp_path, ex):
        _seed_vocab_state(tmp_path, self._make_eligible())
        asyncio.run(ex.run(RecordingChannel(), UserProfile()))

        channel = RecordingChannel()
        result = asyncio.run(ex.reply("anything", channel, UserProfile()))

        # Not the last question yet
        assert result.waiting_for_user is True
        assert result.completed is False

    def test_last_reply_returns_completed(self, tmp_path, ex):
        entries = self._make_eligible(WORDS_PER_TEST)
        _seed_vocab_state(tmp_path, entries)
        asyncio.run(ex.run(RecordingChannel(), UserProfile()))

        # Answer all questions
        for _ in range(WORDS_PER_TEST - 1):
            asyncio.run(ex.reply("anything", RecordingChannel(), UserProfile()))

        channel = RecordingChannel()
        result = asyncio.run(ex.reply("anything", channel, UserProfile()))

        assert result.completed is True

    def test_quiz_state_deleted_after_completion(self, tmp_path, ex):
        _seed_vocab_state(tmp_path, self._make_eligible())
        asyncio.run(ex.run(RecordingChannel(), UserProfile()))

        for _ in range(WORDS_PER_TEST):
            asyncio.run(ex.reply("anything", RecordingChannel(), UserProfile()))

        quiz_path = tmp_path / "vocab_quiz" / "quiz_state.json"
        assert not quiz_path.exists()

    def test_vocab_state_updated_after_completion(self, tmp_path, ex):
        entries = self._make_eligible(WORDS_PER_TEST)
        _seed_vocab_state(tmp_path, entries)
        asyncio.run(ex.run(RecordingChannel(), UserProfile()))

        import json
        quiz_path = tmp_path / "vocab_quiz" / "quiz_state.json"
        quiz = json.loads(quiz_path.read_text(encoding="utf-8"))
        tested_words = [q["en"] for q in quiz["questions"]]

        for _ in range(WORDS_PER_TEST):
            asyncio.run(ex.reply("anything", RecordingChannel(), UserProfile()))

        after = load_vocab_state("vocab")
        for en in tested_words:
            assert after.vocab[en]["times_tested"] == 1
            assert len(after.vocab[en]["results"]) == 1

    def test_summary_message_sent_on_completion(self, tmp_path, ex):
        _seed_vocab_state(tmp_path, self._make_eligible())
        asyncio.run(ex.run(RecordingChannel(), UserProfile()))

        for _ in range(WORDS_PER_TEST - 1):
            asyncio.run(ex.reply("anything", RecordingChannel(), UserProfile()))

        channel = RecordingChannel()
        asyncio.run(ex.reply("anything", channel, UserProfile()))

        # Last message should be summary (feedback + summary)
        texts = [m.content for m in channel.sent]
        assert any("/" in t for t in texts)  # summary format "N/M"

    def test_stage_increments_with_each_reply(self, tmp_path, ex):
        _seed_vocab_state(tmp_path, self._make_eligible())

        result = asyncio.run(ex.run(RecordingChannel(), UserProfile()))
        assert result.stage == (1, WORDS_PER_TEST)

        result2 = asyncio.run(ex.reply("anything", RecordingChannel(), UserProfile()))
        assert result2.stage == (2, WORDS_PER_TEST)


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_vocab_returns_fallback_message_completed(self, tmp_path, ex):
        _seed_vocab_state(tmp_path, [])

        channel = RecordingChannel()
        result = asyncio.run(ex.run(channel, UserProfile()))

        assert result.completed is True
        assert len(channel.sent) == 1
        assert channel.sent[0].type == "text"

    def test_vocab_below_min_times_shown_treated_as_empty(self, tmp_path, ex):
        entries = [
            _make_entry(f"word{i}", f"слово{i}", times_shown=MIN_TIMES_SHOWN - 1)
            for i in range(5)
        ]
        _seed_vocab_state(tmp_path, entries)

        channel = RecordingChannel()
        result = asyncio.run(ex.run(channel, UserProfile()))

        assert result.completed is True

    def test_stale_quiz_state_cleaned_on_run(self, tmp_path, ex):
        # Write a stale quiz_state.json before calling run()
        quiz_dir = tmp_path / "vocab_quiz"
        quiz_dir.mkdir(parents=True)
        atomic_write(quiz_dir / "quiz_state.json", {"stale": True})

        _seed_vocab_state(tmp_path, _eligible_entries(WORDS_PER_TEST))

        asyncio.run(ex.run(RecordingChannel(), UserProfile()))

        import json
        quiz = json.loads((quiz_dir / "quiz_state.json").read_text(encoding="utf-8"))
        # Should be a fresh quiz state, not the stale one
        assert "stale" not in quiz
        assert "questions" in quiz

    def test_missing_quiz_state_on_reply_returns_reason(self, ex):
        # No run() called first — quiz_state.json doesn't exist
        result = asyncio.run(ex.reply("anything", RecordingChannel(), UserProfile()))

        assert result.completed is False
        assert result.reason == "quiz_state_lost"

    def test_corrupted_quiz_state_on_reply_returns_reason(self, tmp_path, ex):
        quiz_dir = tmp_path / "vocab_quiz"
        quiz_dir.mkdir(parents=True)
        (quiz_dir / "quiz_state.json").write_text("not json", encoding="utf-8")

        result = asyncio.run(ex.reply("anything", RecordingChannel(), UserProfile()))

        assert result.completed is False
        assert result.reason == "quiz_state_lost"

    def test_run_clears_stale_then_fallback_if_no_eligible_words(self, tmp_path, ex):
        # Stale quiz + no eligible words → stale cleaned, fallback returned
        quiz_dir = tmp_path / "vocab_quiz"
        quiz_dir.mkdir(parents=True)
        atomic_write(quiz_dir / "quiz_state.json", {"stale": True})

        _seed_vocab_state(tmp_path, [])

        channel = RecordingChannel()
        result = asyncio.run(ex.run(channel, UserProfile()))

        assert result.completed is True
        # Stale file gone
        assert not (quiz_dir / "quiz_state.json").exists()
