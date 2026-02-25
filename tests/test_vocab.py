"""
Unit tests for VocabExercise.

Run from the english-tutor directory:
    python -m pytest tests/test_vocab.py -v
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from exercises.vocab import (
    VocabExercise,
    VocabState,
    ACTIVE_POOL_SIZE,
    GRADUATION_SHOW_COUNT,
    STATE_FILE,
    TOPICS_FILE,
    TOPIC_FULL_THRESHOLD,
    WORD_BANK_FILE,
    WORDS_PER_SESSION,
)
from config import set_data_path
from models import UserProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_active_vocab(n: int) -> dict:
    """Return a vocab dict with n active (is_learning=True) words."""
    return {
        f"word{i}": {
            "en": f"word{i}",
            "ru": f"ru{i}",
            "topic": "greetings",
            "difficulty": "A1",
            "is_learning": True,
            "times_shown": 0,
            "times_tested": 0,
            "results": [],
            "last_seen": None,
        }
        for i in range(n)
    }


def _make_graduated_vocab(n: int) -> dict:
    """Return a vocab dict with n graduated (is_learning=False) words."""
    return {
        f"grad{i}": {
            "en": f"grad{i}",
            "ru": f"gru{i}",
            "topic": "greetings",
            "difficulty": "A1",
            "is_learning": False,
            "times_shown": GRADUATION_SHOW_COUNT,
            "times_tested": 0,
            "results": [],
            "last_seen": None,
        }
        for i in range(n)
    }


# ---------------------------------------------------------------------------
# First-run initialisation
# ---------------------------------------------------------------------------


class TestVocabFirstRun:
    def test_first_run_initializes_files_from_seed(self, tmp_path):
        """On a fresh data path, get_content creates word_bank, topics, and state files."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        asyncio.run(ex.get_content(UserProfile()))

        vocab_dir = tmp_path / "vocab"
        assert (vocab_dir / WORD_BANK_FILE).exists()
        assert (vocab_dir / TOPICS_FILE).exists()
        assert (vocab_dir / STATE_FILE).exists()

        # All three are valid JSON dicts
        for name in (WORD_BANK_FILE, TOPICS_FILE, STATE_FILE):
            data = json.loads((vocab_dir / name).read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_missing_seed_file_raises(self, tmp_path):
        """If the seed file is absent, _load_state propagates FileNotFoundError."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        seed = Path(__file__).parent.parent / "exercises" / "data" / "word_bank_seed.json"
        with patch("shutil.copy2", side_effect=FileNotFoundError("seed gone")):
            with pytest.raises(FileNotFoundError):
                ex._load_state()


# ---------------------------------------------------------------------------
# Replenishment
# ---------------------------------------------------------------------------


class TestReplenishment:
    def test_empty_pool_is_filled_from_word_bank(self, tmp_path):
        """When active pool is empty, replenish pulls words from the selected topic."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        state = ex._load_state()
        assert len(state.vocab) == 0

        ex._replenish_pool(state)

        active = [w for w in state.vocab.values() if w["is_learning"]]
        assert len(active) > 0
        for w in active:
            assert w["is_learning"] is True
            assert w["times_shown"] == 0

    def test_full_pool_is_not_replenished(self, tmp_path):
        """When active count already equals ACTIVE_POOL_SIZE, no words are added."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        state = ex._load_state()

        state.vocab = _make_active_vocab(ACTIVE_POOL_SIZE)
        state.word_bank = {
            "greetings": [{"en": "hello", "ru": "privet", "difficulty": "A1"}]
        }
        state.topics = {"greetings": {"started": True, "word_count": ACTIVE_POOL_SIZE}}

        ex._replenish_pool(state)

        assert "hello" not in state.vocab
        assert len(state.vocab) == ACTIVE_POOL_SIZE

    def test_existing_words_are_not_duplicated(self, tmp_path):
        """Words already in vocab are skipped during replenishment."""
        set_data_path(tmp_path)
        ex = VocabExercise()

        vocab = {
            "hello": {
                "en": "hello",
                "ru": "privet",
                "topic": "greetings",
                "difficulty": "A1",
                "is_learning": True,
                "times_shown": 0,
                "times_tested": 0,
                "results": [],
                "last_seen": None,
            }
        }
        word_bank = {
            "greetings": [
                {"en": "hello", "ru": "privet", "difficulty": "A1"},
                {"en": "goodbye", "ru": "poka", "difficulty": "A1"},
            ]
        }
        topics = {"greetings": {"started": True, "word_count": 1}}
        state = VocabState(vocab=vocab, word_bank=word_bank, topics=topics)

        ex._replenish_pool(state)

        assert list(state.vocab.keys()).count("hello") == 1
        assert "goodbye" in state.vocab


# ---------------------------------------------------------------------------
# Graduation
# ---------------------------------------------------------------------------


class TestGraduation:
    def test_word_graduates_after_threshold(self, tmp_path):
        """A word shown >= GRADUATION_SHOW_COUNT times becomes is_learning=False."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        state = ex._load_state()
        ex._replenish_pool(state)

        key = next(iter(state.vocab))
        state.vocab[key]["times_shown"] = GRADUATION_SHOW_COUNT - 1
        assert state.vocab[key]["is_learning"] is True

        state.vocab[key]["times_shown"] = GRADUATION_SHOW_COUNT
        ex._check_graduations(state.vocab)
        assert state.vocab[key]["is_learning"] is False

    def test_word_below_threshold_stays_learning(self, tmp_path):
        """A word shown fewer than GRADUATION_SHOW_COUNT times stays active."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        vocab = _make_active_vocab(1)
        key = next(iter(vocab))
        vocab[key]["times_shown"] = GRADUATION_SHOW_COUNT - 1

        ex._check_graduations(vocab)

        assert vocab[key]["is_learning"] is True

    def test_already_graduated_word_is_not_changed(self, tmp_path):
        """_check_graduations does not re-process already-graduated words."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        vocab = _make_graduated_vocab(1)
        key = next(iter(vocab))
        vocab[key]["times_shown"] = GRADUATION_SHOW_COUNT + 10

        ex._check_graduations(vocab)

        # Must remain False and not flip back
        assert vocab[key]["is_learning"] is False


# ---------------------------------------------------------------------------
# Topic selection
# ---------------------------------------------------------------------------


class TestTopicSelection:
    def test_starts_first_topic_when_none_started(self, tmp_path):
        """When no topic is started, _select_topic starts the first one."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        state = ex._load_state()

        assert all(not t["started"] for t in state.topics.values())

        selected = ex._select_topic(state.topics)
        # The first key in the seed file is 'greetings'; dict order is preserved.
        assert selected == "greetings"
        assert state.topics["greetings"]["started"] is True

    def test_picks_started_topic_with_lowest_word_count(self, tmp_path):
        """Among started topics, picks the one with the fewest words."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        state = ex._load_state()

        state.topics["greetings"]["started"] = True
        state.topics["greetings"]["word_count"] = 10
        state.topics["family"]["started"] = True
        state.topics["family"]["word_count"] = 3

        selected = ex._select_topic(state.topics)
        assert selected == "family"

    def test_full_topic_causes_next_unstarted_to_start(self, tmp_path):
        """When the best started topic reaches TOPIC_FULL_THRESHOLD, the next unstarted topic is started."""
        set_data_path(tmp_path)
        ex = VocabExercise()

        topics = {
            "greetings": {"started": True, "word_count": TOPIC_FULL_THRESHOLD},
            "family": {"started": False, "word_count": 0},
        }

        selected = ex._select_topic(topics)
        assert selected == "family"
        assert topics["family"]["started"] is True

    def test_all_topics_full_and_started_returns_none(self, tmp_path):
        """When every topic is started and at TOPIC_FULL_THRESHOLD, returns None."""
        set_data_path(tmp_path)
        ex = VocabExercise()

        topics = {
            "greetings": {"started": True, "word_count": TOPIC_FULL_THRESHOLD},
            "family": {"started": True, "word_count": TOPIC_FULL_THRESHOLD},
        }

        assert ex._select_topic(topics) is None

    def test_empty_topics_returns_none(self, tmp_path):
        """An empty topics dict should return None without crashing."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        assert ex._select_topic({}) is None


# ---------------------------------------------------------------------------
# Word picking (_pick_words)
# ---------------------------------------------------------------------------


class TestPickWords:
    def test_normal_run_returns_exactly_words_per_session(self, tmp_path):
        """With enough active words, _pick_words returns exactly WORDS_PER_SESSION words."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        state = VocabState(
            vocab=_make_active_vocab(WORDS_PER_SESSION + 5),
            word_bank={},
            topics={},
        )

        words = ex._pick_words(state)

        assert len(words) == WORDS_PER_SESSION

    def test_fewer_active_than_session_size_returns_all(self, tmp_path):
        """When fewer active words exist than WORDS_PER_SESSION, all of them are returned."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        n = WORDS_PER_SESSION - 2
        state = VocabState(vocab=_make_active_vocab(n), word_bank={}, topics={})

        # Force no review slot so the result only contains active words
        with patch("random.random", return_value=1.0):
            words = ex._pick_words(state)

        assert len(words) == n

    def test_review_slot_includes_one_graduated_word(self, tmp_path):
        """When random.random() < REVIEW_PROBABILITY, one graduated word appears in results."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        vocab = {**_make_active_vocab(10), **_make_graduated_vocab(5)}
        state = VocabState(vocab=vocab, word_bank={}, topics={})

        # Force random.random() below REVIEW_PROBABILITY (0.2)
        with patch("random.random", return_value=0.1):
            words = ex._pick_words(state)

        graduated_in_result = [w for w in words if not w["is_learning"]]
        assert len(graduated_in_result) == 1
        assert len(words) == WORDS_PER_SESSION

    def test_no_review_slot_when_random_above_threshold(self, tmp_path):
        """When random.random() >= REVIEW_PROBABILITY, no graduated word is included."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        vocab = {**_make_active_vocab(10), **_make_graduated_vocab(5)}
        state = VocabState(vocab=vocab, word_bank={}, topics={})

        with patch("random.random", return_value=0.9):
            words = ex._pick_words(state)

        graduated_in_result = [w for w in words if not w["is_learning"]]
        assert len(graduated_in_result) == 0

    def test_empty_vocab_returns_empty_list(self, tmp_path):
        """With no words at all, _pick_words returns []."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        state = VocabState(vocab={}, word_bank={}, topics={})

        words = ex._pick_words(state)

        assert words == []

    def test_all_graduated_no_review_slot_returns_empty(self, tmp_path):
        """All words graduated and review slot not triggered yields empty list."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        state = VocabState(vocab=_make_graduated_vocab(10), word_bank={}, topics={})

        with patch("random.random", return_value=1.0):
            words = ex._pick_words(state)

        assert words == []

    def test_never_returns_more_than_words_per_session(self, tmp_path):
        """Result list is always capped at WORDS_PER_SESSION regardless of pool size."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        # Large active pool
        vocab = {**_make_active_vocab(ACTIVE_POOL_SIZE), **_make_graduated_vocab(20)}
        state = VocabState(vocab=vocab, word_bank={}, topics={})

        for seed_val in [0.05, 0.5, 0.95]:
            with patch("random.random", return_value=seed_val):
                words = ex._pick_words(state)
            assert len(words) <= WORDS_PER_SESSION


# ---------------------------------------------------------------------------
# Fallback message
# ---------------------------------------------------------------------------


class TestFallbackMessage:
    def test_empty_words_returns_fallback_message_not_markdown(self, tmp_path):
        """When _pick_words returns [], get_content sends the Russian fallback message."""
        set_data_path(tmp_path)

        class EmptyPickExercise(VocabExercise):
            def _load_state(self):
                return VocabState(
                    vocab=_make_graduated_vocab(3),
                    word_bank={},
                    topics={},
                )

            def _replenish_pool(self, state):
                pass  # nothing to add

        ex = EmptyPickExercise()
        with patch("random.random", return_value=1.0):  # no review slot
            messages = asyncio.run(ex.get_content(UserProfile()))

        assert len(messages) == 1
        # Fallback message has no parse_mode
        assert messages[0].parse_mode is None
        # State must NOT be saved (no _save_state call on empty path)
        assert not (tmp_path / "vocab" / STATE_FILE).exists()


# ---------------------------------------------------------------------------
# Flashcard format
# ---------------------------------------------------------------------------


class TestFlashcardFormat:
    def test_output_contains_word_translation_pairs(self, tmp_path):
        """The formatted message includes numbered en -- ru pairs."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        messages = asyncio.run(ex.get_content(UserProfile()))

        assert len(messages) == 1
        content = messages[0].content
        assert messages[0].parse_mode == "Markdown"
        assert "**" in content
        assert "—" in content  # em-dash separator

    def test_output_word_count_matches_words_per_session(self, tmp_path):
        """Message contains exactly WORDS_PER_SESSION numbered lines (1. through N.)."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        messages = asyncio.run(ex.get_content(UserProfile()))

        content = messages[0].content
        # Count lines that start with a digit followed by a period
        numbered = [ln for ln in content.splitlines() if ln and ln[0].isdigit() and ". " in ln]
        assert len(numbered) == WORDS_PER_SESSION


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


class TestStatePersistence:
    def test_state_round_trip(self, tmp_path):
        """Running get_content twice loads previously saved state correctly."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        asyncio.run(ex.get_content(UserProfile()))

        vocab_dir = tmp_path / "vocab"
        state_data = json.loads(
            (vocab_dir / STATE_FILE).read_text(encoding="utf-8")
        )
        assert len(state_data) > 0
        shown_once = [w for w in state_data.values() if w["times_shown"] == 1]
        assert len(shown_once) > 0

        # Second run must not create duplicates
        asyncio.run(ex.get_content(UserProfile()))
        state_data_2 = json.loads(
            (vocab_dir / STATE_FILE).read_text(encoding="utf-8")
        )
        assert len(state_data_2) == len(state_data)

    def test_times_shown_increments_across_runs(self, tmp_path):
        """Each get_content call increments times_shown for the words displayed."""
        set_data_path(tmp_path)
        ex = VocabExercise()

        asyncio.run(ex.get_content(UserProfile()))
        vocab_dir = tmp_path / "vocab"
        after_first = json.loads((vocab_dir / STATE_FILE).read_text(encoding="utf-8"))
        max_after_first = max(w["times_shown"] for w in after_first.values())

        asyncio.run(ex.get_content(UserProfile()))
        after_second = json.loads((vocab_dir / STATE_FILE).read_text(encoding="utf-8"))
        max_after_second = max(w["times_shown"] for w in after_second.values())

        assert max_after_second > max_after_first

    def test_topics_file_persisted_after_get_content(self, tmp_path):
        """topics.json is written after get_content so topic state survives a restart."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        asyncio.run(ex.get_content(UserProfile()))

        vocab_dir = tmp_path / "vocab"
        topics_data = json.loads((vocab_dir / TOPICS_FILE).read_text(encoding="utf-8"))
        # At least the first topic must be marked started
        started = [t for t, v in topics_data.items() if v["started"]]
        assert len(started) >= 1

    def test_atomic_write_cleans_up_tmp_on_error(self, tmp_path):
        """If the write fails, no leftover .tmp file should remain."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        state = ex._load_state()

        target = tmp_path / "vocab" / "state.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = target.with_suffix(".tmp")

        with patch("pathlib.Path.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                ex._atomic_write(target, {"hello": "world"})

        assert not tmp_file.exists()


# ---------------------------------------------------------------------------
# Update state
# ---------------------------------------------------------------------------


class TestUpdateState:
    def test_update_state_increments_times_shown(self, tmp_path):
        """_update_state increments times_shown for each shown word."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        vocab = _make_active_vocab(3)
        state = VocabState(vocab=vocab, word_bank={}, topics={})

        shown = [state.vocab["word0"], state.vocab["word1"]]
        ex._update_state(state, shown)

        assert state.vocab["word0"]["times_shown"] == 1
        assert state.vocab["word1"]["times_shown"] == 1
        assert state.vocab["word2"]["times_shown"] == 0

    def test_update_state_sets_last_seen(self, tmp_path):
        """_update_state records a non-None ISO timestamp in last_seen."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        vocab = _make_active_vocab(1)
        state = VocabState(vocab=vocab, word_bank={}, topics={})

        assert state.vocab["word0"]["last_seen"] is None
        ex._update_state(state, [state.vocab["word0"]])
        assert state.vocab["word0"]["last_seen"] is not None

    def test_update_state_ignores_orphan_words(self, tmp_path):
        """Words in the shown list but absent from vocab are silently skipped."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        vocab = _make_active_vocab(1)
        state = VocabState(vocab=vocab, word_bank={}, topics={})

        orphan = {"en": "ghost", "ru": "prizrak", "is_learning": True, "times_shown": 0}
        ex._update_state(state, [orphan])  # must not raise

        assert "ghost" not in state.vocab
        assert state.vocab["word0"]["times_shown"] == 0


# ---------------------------------------------------------------------------
# Global state isolation
# ---------------------------------------------------------------------------


class TestGlobalStateIsolation:
    def test_set_data_path_affects_load_state(self, tmp_path):
        """set_data_path controls which directory _load_state reads from."""
        set_data_path(tmp_path)
        ex = VocabExercise()
        state = ex._load_state()
        # Vocab dir should be created under the tmp_path we passed, not elsewhere
        expected_dir = tmp_path / "vocab"
        assert expected_dir.exists()
        # And no data should have been written to the real data path
        real_path = Path("data/skills/english-tutor/vocab")
        assert not real_path.exists() or not (real_path / STATE_FILE).exists()
