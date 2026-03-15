from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from config import get_data_path, get_student_level
from models import StudentLevel

logger = logging.getLogger(__name__)

VOCAB_STATE_DIR = "vocab"
STATE_FILE = "state.json"
WORD_BANK_FILE = "word_bank.json"
TOPICS_FILE = "topics.json"


@dataclass
class VocabState:
    vocab: dict       # word -> word entry dict
    word_bank: dict   # topic -> list of word entries
    topics: dict      # topic -> {word_count, started}


def load_vocab_state(name: str) -> VocabState:
    """Load vocab state from disk, initialising files on first run."""
    data_dir = get_data_path() / name
    data_dir.mkdir(parents=True, exist_ok=True)

    # Word bank
    word_bank_path = data_dir / WORD_BANK_FILE
    # Known limitation: existing word_bank.json files from before difficulty
    # filtering are not retroactively filtered. The belt-and-suspenders check
    # in _replenish_pool handles this at the pool level.
    if not word_bank_path.exists():
        init_word_bank(word_bank_path)
    word_bank = json.loads(word_bank_path.read_text(encoding="utf-8"))

    # Topics
    topics_path = data_dir / TOPICS_FILE
    if not topics_path.exists():
        topics = {
            topic: {"word_count": 0, "started": False}
            for topic in word_bank
        }
    else:
        topics = json.loads(topics_path.read_text(encoding="utf-8"))

    # Vocab state
    state_path = data_dir / STATE_FILE
    if not state_path.exists():
        vocab = {}
    else:
        vocab = json.loads(state_path.read_text(encoding="utf-8"))

    return VocabState(vocab=vocab, word_bank=word_bank, topics=topics)


def init_word_bank(word_bank_path: Path) -> None:
    """Filter the seed word bank by student level and write to disk."""
    seed_path = Path(__file__).parent / "data" / "word_bank_seed.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    level = get_student_level()
    low, high = level.difficulty_window()
    filtered: dict[str, list] = {}
    for topic, words in seed.items():
        kept = []
        for word in words:
            try:
                word_level = StudentLevel.parse(word["difficulty"])
            except (ValueError, KeyError):
                continue
            if low <= word_level <= high:
                kept.append(word)
        filtered[topic] = kept
    total_words = sum(len(ws) for ws in filtered.values())
    if total_words == 0:
        raise RuntimeError(
            f"Filtered word bank is empty — student level {level} "
            "has no matching words in the seed. Check config.json."
        )
    word_bank_path.write_text(
        json.dumps(filtered, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_vocab_state(name: str, state: VocabState) -> None:
    """Persist vocab and topics to disk."""
    data_dir = get_data_path() / name
    data_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(data_dir / STATE_FILE, state.vocab)
    atomic_write(data_dir / TOPICS_FILE, state.topics)


def atomic_write(path: Path, data: dict) -> None:
    """Write to .tmp first, then replace -- avoids corrupted files on crash."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
