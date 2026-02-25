from __future__ import annotations

import json
import logging
import random
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from models import Message, UserProfile
from config import get_data_path
from exercises.base import Exercise
from exercises.registry import register_exercise

logger = logging.getLogger(__name__)

ACTIVE_POOL_SIZE = 50
WORDS_PER_SESSION = 6
GRADUATION_SHOW_COUNT = 8
REVIEW_PROBABILITY = 0.2
TOPIC_FULL_THRESHOLD = 30

STATE_FILE = "state.json"
WORD_BANK_FILE = "word_bank.json"
TOPICS_FILE = "topics.json"


@dataclass
class VocabState:
    vocab: dict       # word -> word entry dict
    word_bank: dict   # topic -> list of word entries
    topics: dict      # topic -> {word_count, started}


@register_exercise
class VocabExercise(Exercise):
    @property
    def name(self) -> str:
        return "vocab"

    async def get_content(self, profile: UserProfile) -> list[Message]:
        state = self._load_state()
        self._replenish_pool(state)
        words = self._pick_words(state)

        if not words:
            return [
                Message(
                    type="text",
                    content="Словарь пока пуст. Скоро добавим новые слова!",
                )
            ]

        messages = self._format(words)
        try:
            self._update_state(state, words)
            self._save_state(state)
        except Exception:
            logger.exception("Failed to save vocab state; delivering words anyway")
        return messages

    def _load_state(self) -> VocabState:
        data_dir = get_data_path() / self.name
        data_dir.mkdir(parents=True, exist_ok=True)

        # Word bank
        word_bank_path = data_dir / WORD_BANK_FILE
        if not word_bank_path.exists():
            seed_path = Path(__file__).parent / "data" / "word_bank_seed.json"
            shutil.copy2(seed_path, word_bank_path)
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

    def _replenish_pool(self, state: VocabState) -> None:
        active_count = sum(1 for w in state.vocab.values() if w["is_learning"])
        if active_count >= ACTIVE_POOL_SIZE:
            return

        needed = ACTIVE_POOL_SIZE - active_count
        topic = self._select_topic(state.topics)
        if topic is None:
            return

        bank_words = state.word_bank.get(topic, [])
        existing_en = {w["en"] for w in state.vocab.values()}
        added = 0

        for word in bank_words:
            if added >= needed:
                break
            if word["en"] in existing_en:
                continue

            state.vocab[word["en"]] = {
                "en": word["en"],
                "ru": word["ru"],
                "topic": topic,
                "difficulty": word["difficulty"],
                "is_learning": True,
                "times_shown": 0,
                "times_tested": 0,
                "results": [],
                "last_seen": None,
            }
            state.topics[topic]["word_count"] += 1
            added += 1

    def _select_topic(self, topics: dict) -> str | None:
        started = [t for t in topics if topics[t]["started"]]

        if not started:
            # Start the first topic
            for t in topics:
                topics[t]["started"] = True
                return t
            return None

        # Find started topic with lowest word_count
        best = min(started, key=lambda t: topics[t]["word_count"])

        if topics[best]["word_count"] >= TOPIC_FULL_THRESHOLD:
            # Start the next unstarted topic
            for t in topics:
                if not topics[t]["started"]:
                    topics[t]["started"] = True
                    return t
            return None

        return best

    def _pick_words(self, state: VocabState) -> list[dict]:
        active = [w for w in state.vocab.values() if w["is_learning"]]
        graduated = [w for w in state.vocab.values() if not w["is_learning"]]

        random.shuffle(active)
        random.shuffle(graduated)

        result: list[dict] = []
        review_slot = (
            1 if graduated and random.random() < REVIEW_PROBABILITY else 0
        )
        active_slots = WORDS_PER_SESSION - review_slot

        result.extend(active[:active_slots])
        if review_slot:
            result.extend(graduated[:review_slot])

        return result[:WORDS_PER_SESSION]

    def _format(self, words: list[dict]) -> list[Message]:
        lines = ["📖 **Словарный запас**", ""]
        for i, word in enumerate(words, 1):
            lines.append(f"{i}. **{word['en']}** — {word['ru']}")
        lines.append("")
        lines.append(
            "Попробуй вспомнить английские слова, прежде чем читать их!"
        )
        content = "\n".join(lines)
        return [Message(type="text", content=content, parse_mode="Markdown")]

    def _update_state(self, state: VocabState, shown: list[dict]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for word in shown:
            key = word["en"]
            if key in state.vocab:
                state.vocab[key]["times_shown"] += 1
                state.vocab[key]["last_seen"] = now
        self._check_graduations(state.vocab)

    def _check_graduations(self, vocab: dict) -> None:
        for word in vocab.values():
            if word["is_learning"] and word["times_shown"] >= GRADUATION_SHOW_COUNT:
                word["is_learning"] = False

    def _save_state(self, state: VocabState) -> None:
        data_dir = get_data_path() / self.name
        data_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write(data_dir / STATE_FILE, state.vocab)
        self._atomic_write(data_dir / TOPICS_FILE, state.topics)

    def _atomic_write(self, path: Path, data: dict) -> None:
        # Write to .tmp first, then replace — avoids corrupted files on crash.
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
