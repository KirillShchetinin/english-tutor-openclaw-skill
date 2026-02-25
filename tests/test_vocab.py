"""
Unit tests for VocabExercise.

Run from the english-tutor directory:
    python -m pytest tests/test_vocab.py -v
"""
from __future__ import annotations

import asyncio
import json
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
# Helpers & fixtures
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


@pytest.fixture()
def vocab_ex(tmp_path):
    """Set data path and return a fresh VocabExercise."""
    set_data_path(tmp_path)
    return VocabExercise()


# ---------------------------------------------------------------------------
# First-run initialisation
# ---------------------------------------------------------------------------


class TestVocabFirstRun:
    def test_first_run_initializes_files_from_seed(self, tmp_path, vocab_ex):
        """On a fresh data path, get_content creates word_bank, topics, and state files."""
        asyncio.run(vocab_ex.get_content(UserProfile()))

        vocab_dir = tmp_path / "vocab"
        for name in (WORD_BANK_FILE, TOPICS_FILE, STATE_FILE):
            path = vocab_dir / name
            assert path.exists()
            assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_missing_seed_file_raises(self, vocab_ex):
        """If the seed file is absent, _load_state propagates FileNotFoundError."""
        with patch("shutil.copy2", side_effect=FileNotFoundError("seed gone")):
            with pytest.raises(FileNotFoundError):
                vocab_ex._load_state()


# ---------------------------------------------------------------------------
# Replenishment
# ---------------------------------------------------------------------------


class TestReplenishment:
    def test_empty_pool_is_filled_from_word_bank(self, vocab_ex):
        """When active pool is empty, replenish pulls words from the selected topic."""
        state = vocab_ex._load_state()
        assert len(state.vocab) == 0

        vocab_ex._replenish_pool(state)

        active = [w for w in state.vocab.values() if w["is_learning"]]
        assert len(active) > 0
        for w in active:
            assert w["is_learning"] is True
            assert w["times_shown"] == 0

    def test_full_pool_is_not_replenished(self, vocab_ex):
        """When active count already equals ACTIVE_POOL_SIZE, no words are added."""
        state = vocab_ex._load_state()
        state.vocab = _make_active_vocab(ACTIVE_POOL_SIZE)
        state.word_bank = {
            "greetings": [{"en": "hello", "ru": "privet", "difficulty": "A1"}]
        }
        state.topics = {"greetings": {"started": True, "word_count": ACTIVE_POOL_SIZE}}

        vocab_ex._replenish_pool(state)

        assert "hello" not in state.vocab
        assert len(state.vocab) == ACTIVE_POOL_SIZE

    def test_existing_words_are_not_duplicated(self, vocab_ex):
        """Words already in vocab are skipped during replenishment."""
        state = VocabState(
            vocab={
                "hello": {
                    "en": "hello", "ru": "privet", "topic": "greetings",
                    "difficulty": "A1", "is_learning": True, "times_shown": 0,
                    "times_tested": 0, "results": [], "last_seen": None,
                }
            },
            word_bank={
                "greetings": [
                    {"en": "hello", "ru": "privet", "difficulty": "A1"},
                    {"en": "goodbye", "ru": "poka", "difficulty": "A1"},
                ]
            },
            topics={"greetings": {"started": True, "word_count": 1}},
        )

        vocab_ex._replenish_pool(state)

        assert list(state.vocab.keys()).count("hello") == 1
        assert "goodbye" in state.vocab


# ---------------------------------------------------------------------------
# Graduation
# ---------------------------------------------------------------------------


class TestGraduation:
    def test_graduation_lifecycle(self, vocab_ex):
        """Words graduate at threshold and stay graduated; below threshold stays active."""
        vocab = _make_active_vocab(1)
        key = next(iter(vocab))

        # Below threshold — stays learning
        vocab[key]["times_shown"] = GRADUATION_SHOW_COUNT - 1
        vocab_ex._check_graduations(vocab)
        assert vocab[key]["is_learning"] is True

        # At threshold — graduates
        vocab[key]["times_shown"] = GRADUATION_SHOW_COUNT
        vocab_ex._check_graduations(vocab)
        assert vocab[key]["is_learning"] is False

        # Already graduated — stays graduated (no flip-back)
        vocab[key]["times_shown"] = GRADUATION_SHOW_COUNT + 10
        vocab_ex._check_graduations(vocab)
        assert vocab[key]["is_learning"] is False


# ---------------------------------------------------------------------------
# Topic selection
# ---------------------------------------------------------------------------


class TestTopicSelection:
    def test_starts_first_topic_when_none_started(self, vocab_ex):
        """When no topic is started, _select_topic starts the first one."""
        state = vocab_ex._load_state()
        assert all(not t["started"] for t in state.topics.values())

        selected = vocab_ex._select_topic(state.topics)
        assert selected == "greetings"
        assert state.topics["greetings"]["started"] is True

    def test_picks_started_topic_with_lowest_word_count(self, vocab_ex):
        """Among started topics, picks the one with the fewest words."""
        state = vocab_ex._load_state()
        state.topics["greetings"]["started"] = True
        state.topics["greetings"]["word_count"] = 10
        state.topics["family"]["started"] = True
        state.topics["family"]["word_count"] = 3

        assert vocab_ex._select_topic(state.topics) == "family"

    def test_full_topic_causes_next_unstarted_to_start(self, vocab_ex):
        """When the best started topic reaches TOPIC_FULL_THRESHOLD, the next unstarted topic is started."""
        topics = {
            "greetings": {"started": True, "word_count": TOPIC_FULL_THRESHOLD},
            "family": {"started": False, "word_count": 0},
        }

        selected = vocab_ex._select_topic(topics)
        assert selected == "family"
        assert topics["family"]["started"] is True

    def test_returns_none_when_exhausted(self, vocab_ex):
        """Returns None for empty topics and when all topics are full."""
        assert vocab_ex._select_topic({}) is None

        all_full = {
            "greetings": {"started": True, "word_count": TOPIC_FULL_THRESHOLD},
            "family": {"started": True, "word_count": TOPIC_FULL_THRESHOLD},
        }
        assert vocab_ex._select_topic(all_full) is None


# ---------------------------------------------------------------------------
# Word picking (_pick_words)
# ---------------------------------------------------------------------------


class TestPickWords:
    def test_returns_exactly_words_per_session(self, vocab_ex):
        """With enough active words, returns exactly WORDS_PER_SESSION, never more."""
        state = VocabState(
            vocab={**_make_active_vocab(ACTIVE_POOL_SIZE), **_make_graduated_vocab(20)},
            word_bank={}, topics={},
        )

        for seed_val in [0.05, 0.5, 0.95]:
            with patch("random.random", return_value=seed_val):
                words = vocab_ex._pick_words(state)
            assert len(words) == WORDS_PER_SESSION

    def test_fewer_active_than_session_size_returns_all(self, vocab_ex):
        """When fewer active words exist than WORDS_PER_SESSION, all of them are returned."""
        n = WORDS_PER_SESSION - 2
        state = VocabState(vocab=_make_active_vocab(n), word_bank={}, topics={})

        with patch("random.random", return_value=1.0):
            words = vocab_ex._pick_words(state)

        assert len(words) == n

    def test_review_slot_controlled_by_random(self, vocab_ex):
        """Review slot includes graduated word when random < threshold, excludes otherwise."""
        vocab = {**_make_active_vocab(10), **_make_graduated_vocab(5)}
        state = VocabState(vocab=vocab, word_bank={}, topics={})

        # Below threshold — one graduated word included
        with patch("random.random", return_value=0.1):
            words = vocab_ex._pick_words(state)
        graduated = [w for w in words if not w["is_learning"]]
        assert len(graduated) == 1
        assert len(words) == WORDS_PER_SESSION

        # Above threshold — no graduated words
        with patch("random.random", return_value=0.9):
            words = vocab_ex._pick_words(state)
        graduated = [w for w in words if not w["is_learning"]]
        assert len(graduated) == 0

    def test_empty_and_all_graduated_returns_empty(self, vocab_ex):
        """Returns [] for empty vocab and for all-graduated with no review slot."""
        assert vocab_ex._pick_words(VocabState(vocab={}, word_bank={}, topics={})) == []

        state = VocabState(vocab=_make_graduated_vocab(10), word_bank={}, topics={})
        with patch("random.random", return_value=1.0):
            assert vocab_ex._pick_words(state) == []


# ---------------------------------------------------------------------------
# Fallback message
# ---------------------------------------------------------------------------


class TestFallbackMessage:
    def test_empty_words_returns_fallback_message(self, tmp_path, vocab_ex):
        """When _pick_words returns [], get_content sends the Russian fallback."""

        class EmptyPickExercise(VocabExercise):
            def _load_state(self):
                return VocabState(vocab=_make_graduated_vocab(3), word_bank={}, topics={})
            def _replenish_pool(self, state):
                pass

        ex = EmptyPickExercise()
        with patch("random.random", return_value=1.0):
            messages = asyncio.run(ex.get_content(UserProfile()))

        assert len(messages) == 1
        assert messages[0].parse_mode is None
        assert not (tmp_path / "vocab" / STATE_FILE).exists()


# ---------------------------------------------------------------------------
# Flashcard format
# ---------------------------------------------------------------------------


class TestFlashcardFormat:
    def test_output_format_and_word_count(self, vocab_ex):
        """Message is Markdown with em-dash pairs and exactly WORDS_PER_SESSION lines."""
        messages = asyncio.run(vocab_ex.get_content(UserProfile()))

        assert len(messages) == 1
        content = messages[0].content
        assert messages[0].parse_mode == "Markdown"
        assert "**" in content
        assert "—" in content

        numbered = [ln for ln in content.splitlines() if ln and ln[0].isdigit() and ". " in ln]
        assert len(numbered) == WORDS_PER_SESSION


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


class TestStatePersistence:
    def test_state_survives_across_runs(self, tmp_path, vocab_ex):
        """State round-trips correctly: times_shown increments, no duplicates, topics persisted."""
        asyncio.run(vocab_ex.get_content(UserProfile()))

        vocab_dir = tmp_path / "vocab"
        after_first = json.loads((vocab_dir / STATE_FILE).read_text(encoding="utf-8"))
        assert len(after_first) > 0
        assert any(w["times_shown"] == 1 for w in after_first.values())

        # Second run — no duplicates, times_shown increases
        asyncio.run(vocab_ex.get_content(UserProfile()))
        after_second = json.loads((vocab_dir / STATE_FILE).read_text(encoding="utf-8"))
        assert len(after_second) == len(after_first)
        max_first = max(w["times_shown"] for w in after_first.values())
        max_second = max(w["times_shown"] for w in after_second.values())
        assert max_second > max_first

        # Topics file persisted with at least one started topic
        topics = json.loads((vocab_dir / TOPICS_FILE).read_text(encoding="utf-8"))
        assert any(v["started"] for v in topics.values())

    def test_atomic_write_cleans_up_tmp_on_error(self, tmp_path, vocab_ex):
        """If the write fails, no leftover .tmp file should remain."""
        vocab_ex._load_state()

        target = tmp_path / "vocab" / "state.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = target.with_suffix(".tmp")

        with patch("pathlib.Path.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                vocab_ex._atomic_write(target, {"hello": "world"})

        assert not tmp_file.exists()


# ---------------------------------------------------------------------------
# Update state
# ---------------------------------------------------------------------------


class TestUpdateState:
    def test_update_state_effects(self, vocab_ex):
        """_update_state increments times_shown, sets last_seen, and skips orphans."""
        vocab = _make_active_vocab(3)
        state = VocabState(vocab=vocab, word_bank={}, topics={})

        shown = [state.vocab["word0"], state.vocab["word1"]]
        orphan = {"en": "ghost", "ru": "prizrak", "is_learning": True, "times_shown": 0}
        vocab_ex._update_state(state, shown + [orphan])

        # Shown words updated
        assert state.vocab["word0"]["times_shown"] == 1
        assert state.vocab["word0"]["last_seen"] is not None
        assert state.vocab["word1"]["times_shown"] == 1
        assert state.vocab["word1"]["last_seen"] is not None

        # Not-shown word untouched
        assert state.vocab["word2"]["times_shown"] == 0
        assert state.vocab["word2"]["last_seen"] is None

        # Orphan silently skipped
        assert "ghost" not in state.vocab
