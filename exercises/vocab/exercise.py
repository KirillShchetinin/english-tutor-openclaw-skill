from __future__ import annotations

import random
from datetime import datetime, timezone

from channels.base import OutputChannel
from models import Message, StudentLevel, UserProfile
from config import get_student_level
from messages import VOCAB_EMPTY, VOCAB_HEADER, VOCAB_RECALL_HINT
from exercises.base import Exercise, RunResult
from exercises.registry import register_exercise
from exercises.vocab.helpers import (
    VocabState,
    load_vocab_state,
    save_vocab_state,
)

import logging

logger = logging.getLogger(__name__)

ACTIVE_POOL_SIZE = 50
WORDS_PER_SESSION = 10
REVIEW_PROBABILITY = 0.2
TOPIC_FULL_THRESHOLD = 30


@register_exercise
class VocabExercise(Exercise):
    @property
    def name(self) -> str:
        return "vocab"

    async def run(self, channel: OutputChannel, profile: UserProfile) -> RunResult:
        state = load_vocab_state(self.name)
        self._replenish_pool(state)
        words = self._pick_words(state)

        if not words:
            await channel.send(
                Message(
                    type="text",
                    content=VOCAB_EMPTY,
                )
            )
            return RunResult(completed=True)

        for msg in self._format(words):
            await channel.send(msg)

        try:
            self._update_state(state, words)
            save_vocab_state(self.name, state)
        except Exception:
            logger.exception("Failed to save vocab state; delivering words anyway")
        return RunResult(completed=True)

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

        level = get_student_level()
        low, high = level.difficulty_window()

        for word in bank_words:
            if added >= needed:
                break
            if word["en"] in existing_en:
                continue
            try:
                word_level = StudentLevel.parse(word["difficulty"])
            except (ValueError, KeyError):
                continue
            if not (low <= word_level <= high):
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

        if added == 0:
            # All bank words already in vocab; mark topic as full so
            # _select_topic moves on to the next one.
            state.topics[topic]["word_count"] = TOPIC_FULL_THRESHOLD

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
        lines = [VOCAB_HEADER, ""]
        for i, word in enumerate(words, 1):
            lines.append(f"{i}. **{word['en']}** — {word['ru']}")
        lines.append("")
        lines.append(VOCAB_RECALL_HINT)
        content = "\n".join(lines)
        return [Message(type="text", content=content, parse_mode="Markdown")]

    def _update_state(self, state: VocabState, shown: list[dict]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for word in shown:
            key = word["en"]
            if key in state.vocab:
                state.vocab[key]["times_shown"] += 1
                state.vocab[key]["last_seen"] = now
