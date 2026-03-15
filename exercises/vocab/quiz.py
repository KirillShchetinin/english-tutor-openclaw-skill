from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from channels.base import OutputChannel
from config import get_data_path
from exercises.base import InteractiveExercise, RunResult
from exercises.registry import register_exercise
from exercises.vocab.helpers import (
    VOCAB_STATE_DIR,
    VocabState,
    atomic_write,
    load_vocab_state,
    save_vocab_state,
)
from messages import (
    VOCAB_TEST_CORRECT,
    VOCAB_TEST_EMPTY,
    VOCAB_TEST_HEADER,
    VOCAB_TEST_INCORRECT,
    VOCAB_TEST_QUESTION,
    VOCAB_TEST_SUMMARY,
)
from models import Message, UserProfile

logger = logging.getLogger(__name__)


# -- answer evaluation -----------------------------------------------------

@dataclass
class AnswerResult:
    correct: bool
    expected: str       # normalized
    user_answer: str    # normalized
    distance: int       # Levenshtein distance


def _normalize(text: str) -> str:
    """Strip, lowercase, collapse multiple whitespace to single space."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _levenshtein(a: str, b: str) -> int:
    """Standard DP Levenshtein distance."""
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n

    prev = list(range(m + 1))
    curr = [0] * (m + 1)

    for i in range(1, n + 1):
        curr[0] = i
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,       # deletion
                curr[j - 1] + 1,   # insertion
                prev[j - 1] + cost  # substitution
            )
        prev, curr = curr, prev

    return prev[m]


def evaluate_answer(user_input: str, expected: str) -> AnswerResult:
    """Evaluate a user's answer against the expected answer.

    Uses exact match first, then Levenshtein distance with a threshold
    based on expected word length (1 for short words, 2 for longer).
    """
    norm_user = _normalize(user_input)
    norm_expected = _normalize(expected)

    if not norm_expected or not norm_user:
        return AnswerResult(
            correct=False,
            expected=norm_expected,
            user_answer=norm_user,
            distance=len(norm_expected) if norm_expected else 0,
        )

    if norm_user == norm_expected:
        return AnswerResult(
            correct=True,
            expected=norm_expected,
            user_answer=norm_user,
            distance=0,
        )

    dist = _levenshtein(norm_user, norm_expected)
    threshold = 1 if len(norm_expected) <= 4 else 2

    return AnswerResult(
        correct=dist <= threshold,
        expected=norm_expected,
        user_answer=norm_user,
        distance=dist,
    )


# -- constants -------------------------------------------------------------

WORDS_PER_TEST = 5
LEARNING_SLOTS = 4
REVIEW_SLOTS = 1
MIN_TIMES_SHOWN = 2       # minimum exposure before test-eligible
GRADUATION_WINDOW = 4
GRADUATION_THRESHOLD = 3


@register_exercise
class VocabQuizExercise(InteractiveExercise):
    @property
    def name(self) -> str:
        return "vocab_quiz"

    # -- quiz state persistence ----------------------------------------

    def _quiz_dir(self) -> Path:
        return get_data_path() / self.name

    def _load_quiz_state(self) -> dict | None:
        path = self._quiz_dir() / "quiz_state.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            path.unlink(missing_ok=True)
            return None

    def _save_quiz_state(self, quiz: dict) -> None:
        self._quiz_dir().mkdir(parents=True, exist_ok=True)
        atomic_write(self._quiz_dir() / "quiz_state.json", quiz)

    def _delete_quiz_state(self) -> None:
        path = self._quiz_dir() / "quiz_state.json"
        path.unlink(missing_ok=True)

    # -- word selection ------------------------------------------------

    def _current_topic(self, state: VocabState) -> str | None:
        """Most recently started topic that still has active learning words."""
        started = [t for t in state.topics if state.topics[t]["started"]]
        for topic in reversed(started):
            if any(
                w["topic"] == topic and w["is_learning"]
                and w["times_shown"] >= MIN_TIMES_SHOWN
                for w in state.vocab.values()
            ):
                return topic
        return None

    def _pick_test_words(self, state: VocabState) -> list[dict]:
        # Focus on the most recently started topic with eligible words.
        topic = self._current_topic(state)

        learning = [
            w for w in state.vocab.values()
            if w["is_learning"] and w["times_shown"] >= MIN_TIMES_SHOWN
            and (topic is None or w["topic"] == topic)
        ]
        review = [
            w for w in state.vocab.values()
            if not w["is_learning"]
        ]

        learning.sort(key=lambda w: w["times_tested"])
        review.sort(key=lambda w: w["times_tested"])

        selected: list[dict] = []

        learning_take = min(LEARNING_SLOTS, len(learning))
        selected.extend(learning[:learning_take])

        review_take = min(REVIEW_SLOTS, len(review))
        selected.extend(review[:review_take])

        # Fallback: fill remaining capacity from the other pool
        total = len(selected)
        if total < WORDS_PER_TEST:
            remaining = WORDS_PER_TEST - total
            if learning_take < len(learning):
                extra = learning[learning_take:learning_take + remaining]
                selected.extend(extra)
                remaining -= len(extra)
            if remaining > 0 and review_take < len(review):
                extra = review[review_take:review_take + remaining]
                selected.extend(extra)

        selected = selected[:WORDS_PER_TEST]
        random.shuffle(selected)
        return selected

    # -- graduation logic ----------------------------------------------

    def _apply_graduation(self, entry: dict) -> None:
        results = entry.get("results", [])
        last_n = results[-GRADUATION_WINDOW:]
        if len(last_n) >= GRADUATION_WINDOW and sum(last_n) >= GRADUATION_THRESHOLD:
            entry["is_learning"] = False
        # Re-entry: graduated word failed most recent test
        if not entry["is_learning"] and results and not results[-1]:
            entry["is_learning"] = True

    # -- apply results to vocab state ----------------------------------

    def _apply_results(self, questions: list[dict], results: list[bool]) -> None:
        state = load_vocab_state(VOCAB_STATE_DIR)
        now = datetime.now(timezone.utc).isoformat()
        for question, correct in zip(questions, results):
            entry = state.vocab.get(question["en"])
            if entry is None:
                continue
            entry["times_tested"] += 1
            entry["results"].append(correct)
            entry["last_seen"] = now
            self._apply_graduation(entry)
        save_vocab_state(VOCAB_STATE_DIR, state)

    # -- main flow -----------------------------------------------------

    async def run(self, channel: OutputChannel, profile: UserProfile) -> RunResult:
        # Clean up stale quiz state from a previous interrupted run
        if (self._quiz_dir() / "quiz_state.json").exists():
            logger.warning("Stale quiz_state.json found; deleting before new quiz.")
            self._delete_quiz_state()

        state = load_vocab_state(VOCAB_STATE_DIR)
        words = self._pick_test_words(state)

        if not words:
            await channel.send(
                Message(type="text", content=VOCAB_TEST_EMPTY)
            )
            return RunResult(completed=True)

        questions = [{"en": w["en"], "ru": w["ru"]} for w in words]
        total = len(questions)

        quiz = {
            "questions": questions,
            "current_index": 0,
            "results": [],
        }
        self._save_quiz_state(quiz)

        await channel.send(
            Message(type="text", content=VOCAB_TEST_HEADER, parse_mode="Markdown")
        )

        question_msg = Message(
            type="question",
            content=VOCAB_TEST_QUESTION.format(
                index=1, total=total, ru_word=questions[0]["ru"],
            ),
            parse_mode="Markdown",
        )
        ask_id = await channel.send(question_msg)

        return RunResult(
            completed=False,
            waiting_for_user=True,
            stage=(1, total),
            ask_id=ask_id,
        )

    async def reply(self, user_input: str, channel: OutputChannel, profile: UserProfile) -> RunResult:
        quiz = self._load_quiz_state()
        if quiz is None:
            return RunResult(completed=False, reason="quiz_state_lost")

        idx = quiz["current_index"]
        questions = quiz["questions"]
        total = len(questions)

        question = questions[idx]
        result = evaluate_answer(user_input, question["en"])

        quiz["results"].append(result.correct)
        quiz["current_index"] = idx + 1

        if result.correct:
            feedback = Message(
                type="text",
                content=VOCAB_TEST_CORRECT.format(en_word=question["en"]),
            )
        else:
            feedback = Message(
                type="text",
                content=VOCAB_TEST_INCORRECT.format(
                    en_word=question["en"], user_answer=result.user_answer,
                ),
            )
        await channel.send(feedback)

        self._save_quiz_state(quiz)

        if quiz["current_index"] < total:
            next_q = questions[quiz["current_index"]]
            next_msg = Message(
                type="question",
                content=VOCAB_TEST_QUESTION.format(
                    index=quiz["current_index"] + 1,
                    total=total,
                    ru_word=next_q["ru"],
                ),
                parse_mode="Markdown",
            )
            ask_id = await channel.send(next_msg)
            return RunResult(
                completed=False,
                waiting_for_user=True,
                stage=(quiz["current_index"] + 1, total),
                ask_id=ask_id,
            )

        # All questions answered
        num_correct = sum(quiz["results"])
        self._apply_results(questions, quiz["results"])

        await channel.send(
            Message(
                type="text",
                content=VOCAB_TEST_SUMMARY.format(correct=num_correct, total=total),
            )
        )

        self._delete_quiz_state()
        return RunResult(completed=True)
