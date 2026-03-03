# VocabTestExercise — Low-Level Design

## 1. Context

The `VocabExercise` shows 10 words per session (passive exposure). There is no active recall testing yet. The design doc (Phase 2: Test) calls for a testing phase where the user translates Russian → English. The `InteractiveExercise` infrastructure (`run`/`reply` pattern, `ExecutionState` persistence, resume flow) was built but has no real consumer — `vocab_test` will be the first.

## 2. Goal

Create `VocabTestExercise` — a multi-turn interactive exercise that:
1. Picks 5 learning words from vocab state
2. Asks one at a time: "Как по-английски «яблоко»?"
3. Waits for user reply, evaluates answer (fuzzy match)
4. Sends feedback (correct/incorrect)
5. After all 5: sends summary, updates vocab state with test results

---

## 3. Architectural Decisions (Proof Framework Review)

### Decision 1: Separate class (not merged into VocabExercise)

**A1 (SRP) proof:** VocabExercise is `Exercise` (single-turn, push-only). VocabTestExercise is `InteractiveExercise` (multi-turn, requires `reply()`). They have different base classes, different interaction patterns, different change triggers (display format vs quiz mechanics). Merging would force a single class to be both push-only and interactive — `reply()` becomes dead code in non-quiz sessions.

**Decision: Separate class. VocabTestExercise(InteractiveExercise).**

### Decision 2: Data access via shared `vocab_store.py` module

**Problem:** VocabTestExercise must read/write `<data_path>/vocab/state.json`, which VocabExercise currently owns via private methods (`_load_state`, `_save_state`, `_atomic_write`).

**A2/A5 proof:** Direct file access duplicates VocabExercise's 28-line `_load_state()` logic (seed file init, three file loads, directory creation). This creates a hidden dependency — VocabTestExercise knows VocabExercise's file paths by convention, not by contract. A5 says shared mutable state must be extracted.

**Counter-argument:** "YAGNI — just read the file directly, only two consumers."

**Refutation:** The I/O is not trivial. Duplicating seed initialization, three-file loading, and atomic writes means two places to maintain the data format. Extraction cost is low (move existing private methods to module-level functions), while duplication cost is ongoing.

**Decision: Extract `exercises/vocab_store.py` as a shared data access layer. Both exercises import from it. `<data_path>/vocab/` becomes shared infrastructure, not exercise-private state.**

> Note: This resolves the CLAUDE.md "no cross-exercise state access" constraint — neither exercise reads the other's private state; both depend on a shared data module.

### Decision 3: Quiz state in `<data_path>/vocab_test/`

**Rationale:** Quiz progress (which words, current index, accumulated results) is ephemeral per-session state. Vocab state is permanent learning data. Different lifecycles → separate files. Each exercise owns its subdirectory per project convention.

**Decision: `<data_path>/vocab_test/quiz_state.json` for ephemeral quiz progress. Permanent test results (`times_tested`, `results[]`) written to vocab state via `vocab_store`.**

### Decision 4: Answer evaluation in `exercises/answer_eval.py`

**Rationale:** Pure function with zero dependencies. Independently testable. Levenshtein matching is non-trivial (~15-20 lines) and deserves focused edge-case tests without exercise scaffolding.

### Decision 5: Graduation rules coexist, including re-entry

Both graduation mechanisms run independently:
- VocabExercise: `times_shown >= 8` → `is_learning = False`
- VocabTestExercise: `results[-4:]` has 3+ correct → `is_learning = False`
- Re-entry: graduated word tested wrong → `is_learning = True` (explicit product requirement from design doc Section 3.1)

No conflict: exercises run sequentially, VocabTestExercise only picks `is_learning=True` words.

---

## 4. Files

### New files

| File | Purpose |
|---|---|
| `exercises/vocab_store.py` | Shared data access: `VocabState`, `load_vocab_state()`, `save_vocab_state()`, `atomic_write()` — extracted from `vocab.py` |
| `exercises/answer_eval.py` | `evaluate_answer(user_input, expected) -> AnswerResult` pure function + Levenshtein |
| `exercises/vocab_test.py` | `VocabTestExercise(InteractiveExercise)` |
| `tests/test_answer_eval.py` | Answer evaluation unit tests |
| `tests/test_vocab_test.py` | Exercise unit + integration tests |

### Modified files

| File | Change |
|---|---|
| `exercises/vocab.py` | Replace `_load_state`, `_save_state`, `_atomic_write`, `VocabState` with imports from `vocab_store` |
| `exercises/__init__.py` | Add `from exercises.vocab_test import VocabTestExercise` |
| `messages.py` | Add 6 Russian message constants |

---

## 5. Data Structures

### QuizState (`<data_path>/vocab_test/quiz_state.json`)

```json
{
  "questions": [
    {"en": "apple", "ru": "яблоко"},
    {"en": "hello", "ru": "привет"}
  ],
  "current_index": 0,
  "results": []
}
```

**Lifecycle:**
- `run()` creates it (selected words, `current_index=0`, `results=[]`)
- Each `reply()` increments `current_index`, appends to `results`, saves
- Last `reply()`: updates vocab state, sends summary, deletes quiz_state.json
- Stale file on next `run()`: deleted and replaced (safe because `entry.py` clears stale `ExecutionState` before new sessions)

### VocabState (existing, accessed via `vocab_store`)

Word entry fields used by vocab_test:
- READ: `en`, `ru`, `is_learning`, `times_shown`, `times_tested`
- WRITE: `times_tested += 1`, `results.append(bool)`, `last_seen = now`, `is_learning` (graduation/re-entry)

---

## 6. Answer Evaluation

### `exercises/answer_eval.py`

```python
@dataclass
class AnswerResult:
    correct: bool
    expected: str       # normalized
    user_answer: str    # normalized
    distance: int       # Levenshtein distance

def evaluate_answer(user_input: str, expected: str) -> AnswerResult
```

**Algorithm:**
1. Normalize: `strip().lower()`, collapse whitespace
2. Exact match → `correct=True, distance=0`
3. Levenshtein distance:
   - `len(expected) <= 4`: threshold = 1
   - `len(expected) > 4`: threshold = 2
4. Empty input → `correct=False`

**Levenshtein:** Standard DP, ~15 lines. No external dependency.

---

## 7. VocabTestExercise Class

### Constants

```python
WORDS_PER_TEST = 5
GRADUATION_WINDOW = 4
GRADUATION_THRESHOLD = 3
```

### Word Selection (`_pick_words`)

1. Filter `is_learning == True` from vocab state
2. Sort by `times_tested` ascending, then `times_shown` descending (least-tested first, most-shown-but-untested as tiebreaker)
3. Take first `min(5, len(pool))`
4. Shuffle selected words

If 0 words available: send fallback message, return `RunResult(completed=True)`.

### `run(channel, profile) -> RunResult`

1. Clean up stale `quiz_state.json` if exists
2. Load vocab state via `vocab_store`
3. Pick words; if empty → fallback + `completed=True`
4. Save quiz state to `<data_path>/vocab_test/quiz_state.json`
5. Send header message (type="text")
6. Send first question (type="question"): `"(1/5) Как по-английски 'яблоко'?"`
7. Capture `ask_id = await channel.send(question_msg)`
8. Return `RunResult(completed=False, waiting_for_user=True, stage=(1, N), ask_id=ask_id)`

### `reply(user_input, channel, profile) -> RunResult`

1. Load quiz state; if missing → `RunResult(completed=False, reason="quiz_state_lost")`
2. Evaluate answer for `questions[current_index]`
3. Append result to `results[]`, increment `current_index`
4. Send feedback (type="text"): correct or incorrect with the right word
5. Save quiz state
6. If more questions:
   - Send next question (type="question")
   - Return `RunResult(completed=False, waiting_for_user=True, stage=(n+1, N), ask_id=ask_id)`
7. If done:
   - Apply results to vocab state (times_tested, results[], last_seen, graduation/re-entry)
   - Send summary: "Результат: 3/5 правильно!"
   - Delete quiz_state.json
   - Return `RunResult(completed=True)`

### Graduation Logic (`_apply_graduation`)

```python
def _apply_graduation(entry: dict) -> None:
    results = entry.get("results", [])
    last_n = results[-GRADUATION_WINDOW:]
    if len(last_n) >= GRADUATION_WINDOW and sum(last_n) >= GRADUATION_THRESHOLD:
        entry["is_learning"] = False
    # Re-entry: graduated word failed most recent test
    if not entry["is_learning"] and results and not results[-1]:
        entry["is_learning"] = True
```

---

## 8. Multi-Turn Flow

```
Session push (run_session)
  ├── VocabExercise.run() → completed=True (shows words)
  └── VocabTestExercise.run()
        ├── Picks 5 words, saves quiz state
        ├── Sends header + question 1 (type="question")
        └── Returns RunResult(waiting_for_user=True, stage=(1,5))
             → ExecutionState saved: exercise="vocab_test", stage=(1,5)
             → channel.done(status="reply")

User replies → resume_session(user_input="apple", ask_id="abc123")
  └── VocabTestExercise.reply("apple")
        ├── Evaluates answer, sends feedback
        ├── Sends question 2 (type="question")
        └── Returns RunResult(waiting_for_user=True, stage=(2,5))
             → ExecutionState updated: stage=(2,5)
             → channel.done(status="reply")

... (3 more rounds) ...

User replies → resume_session(user_input="water")
  └── VocabTestExercise.reply("water")
        ├── Evaluates last answer, sends feedback
        ├── Sends summary "Результат: 4/5 правильно!"
        ├── Updates vocab/state.json with test results
        ├── Deletes vocab_test/quiz_state.json
        └── Returns RunResult(completed=True)
             → ExecutionState cleared
             → sessions_completed incremented
             → channel.done(status="ok")
```

### RunResult values per turn (N=5)

| Turn | Method | stage | waiting_for_user | completed |
|---|---|---|---|---|
| 0 | `run()` | (1,5) | True | False |
| 1 | `reply()` | (2,5) | True | False |
| 2 | `reply()` | (3,5) | True | False |
| 3 | `reply()` | (4,5) | True | False |
| 4 | `reply()` | (5,5) | True | False |
| 5 | `reply()` | — | — | True |

---

## 9. Messages (`messages.py` additions)

```python
VOCAB_TEST_HEADER = "✏️ **Проверка слов**\nНапиши английское слово по его переводу."
VOCAB_TEST_QUESTION = "({index}/{total}) Как по-английски **'{ru_word}'**?"
VOCAB_TEST_CORRECT = "Правильно! **{en_word}** ✅"
VOCAB_TEST_INCORRECT = "Не совсем. Правильный ответ: **{en_word}** (ты написал: {user_answer})"
VOCAB_TEST_SUMMARY = "Результат: {correct}/{total} правильно!"
VOCAB_TEST_EMPTY = "Пока нет слов для проверки. Скоро появятся!"
```

---

## 10. Edge Cases

| Scenario | Handling |
|---|---|
| `quiz_state.json` exists on `run()` | Delete and start fresh (stale from crashed session) |
| `quiz_state.json` missing on `reply()` | `RunResult(completed=False, reason="quiz_state_lost")` — framework skips |
| `quiz_state.json` corrupted | Catch `JSONDecodeError`, delete, treat as missing |
| vocab `state.json` missing on `run()` | `load_vocab_state()` returns empty dict → fallback message, `completed=True` |
| Fewer than 5 `is_learning` words | Quiz with however many available (1-4) |
| Zero `is_learning` words | Fallback message, `completed=True` |
| Empty user input | `evaluate_answer` handles: `correct=False` |
| `channel.send()` raises | Exception propagates; executor retries (1 attempt per config) |
| Word disappears from vocab state between turns | `_apply_results()` re-reads state; missing keys silently skipped |

---

## 11. Constraints

1. VocabTestExercise must never modify `word_bank.json` or `topics.json`
2. VocabTestExercise must never call replenishment logic
3. `quiz_state.json` must be deleted on quiz completion
4. `run()` must clean up stale `quiz_state.json`
5. Atomic writes for all JSON files
6. All user-facing text in Russian; English only in exercise content
7. Exercise is stateless between instantiations — all state lives in files

---

## 12. Test Strategy

### `tests/test_answer_eval.py`
- Exact match, case insensitive, extra whitespace
- Fuzzy: one typo short word (accept), one typo long word (accept), too many typos (reject)
- Empty input, multi-word phrases, completely wrong answer

### `tests/test_vocab_test.py`

**TestVocabTestRun:** sends header + question, creates quiz_state, handles empty vocab, cleans stale state, handles <5 words

**TestVocabTestReply:** correct/wrong feedback, advances stage, missing quiz_state → soft failure

**TestVocabTestFullQuiz:** run → 5 replies → completion. Verify summary, quiz_state deleted, vocab state updated (times_tested, results[])

**TestGraduation:** graduation after passing threshold, no graduation below threshold, re-entry on wrong answer

**TestWordSelection:** least-tested priority, tiebreaker by most-shown, only is_learning words

---

## 13. Implementation Order

1. Extract `exercises/vocab_store.py` from `exercises/vocab.py` — run existing tests to verify no regression
2. `exercises/answer_eval.py` + `tests/test_answer_eval.py`
3. Message constants in `messages.py`
4. `exercises/vocab_test.py`
5. `exercises/__init__.py` import
6. `tests/test_vocab_test.py` + run all tests
7. Manual: `python -m tests.run_session --force`
