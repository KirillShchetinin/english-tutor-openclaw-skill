# Student Level + Word Bank Replenishment — Design

## 1. Context

The word bank is a one-time copy of a static seed (~250 words). Once all words graduate, the system runs dry. Two problems:

1. **No difficulty control** — words have CEFR tags (`"A1"`, `"B2"`) but nothing filters by them. A beginner sees B2 words.
2. **No replenishment** — `word_bank.json` is never updated after the initial seed copy.

## 2. Student Level Model

CEFR levels (A1, A2, B1, B2, C1, C2) each with sublevels 1–5.
Total: 30 ordinal positions (A1-1 = 1 … C2-5 = 30).

`StudentLevel` frozen dataclass in `models.py`:
- `cefr: str` + `sublevel: int` (1–5)
- `parse("A2-3")` — also handles bare `"A2"` (defaults to sublevel 1 for backward compat)
- `to_ordinal()` / `from_ordinal()` — flat integer for comparison
- Comparison operators (`<`, `<=`, `>`, `>=`)
- `difficulty_window() -> (low, high)`
- `__str__` → `"A2-3"`

### Difficulty Window Rule

Full current CEFR band + 1 sublevel buffer on each side, clamped to valid range.

| Student Level | Window |
|---|---|
| A2-2 | A1-5 → B1-1 |
| A1-3 | A1-1 → A2-1 (clamped at bottom) |
| C2-4 | C1-5 → C2-5 (clamped at top) |

## 3. Configuration

### Python side — `config.py`

```python
from models import StudentLevel
STUDENT_LEVEL: StudentLevel = StudentLevel(cefr="A1", sublevel=1)
```

### OpenClaw side — `<data_path>/config.json`

Written by `core/entry.py` at session start. General-purpose skill config; student level is one field.

```json
{
  "student_level": "A1-1"
}
```

Difficulty window is computed at runtime — not stored.

## 4. Seed → Word Bank: Filtered Copy

Currently `_load_state()` does a blind `shutil.copy2(seed, word_bank.json)` on first run.

Change: load the seed JSON, filter each topic's words by the difficulty window, write the filtered result. The bank starts with only level-appropriate words from day one.

```
seed (all levels, A1–C2)
  → filter by difficulty_window(STUDENT_LEVEL)
  → write word_bank.json (only level-appropriate words)
```

## 5. Difficulty Filtering in `_replenish_pool`

Belt-and-suspenders check for words OpenClaw adds later that might be slightly off-range:

```python
low, high = STUDENT_LEVEL.difficulty_window()
...
word_level = StudentLevel.parse(word["difficulty"])
if not (low <= word_level <= high):
    continue
```

## 6. Word Bank Replenishment (OpenClaw)

The skill never calls an LLM. OpenClaw handles replenishment after each session.

Flow:
```
Session completes → done emitted →
  OpenClaw reads SKILL.md protocol →
  reads <data_path>/config.json for student_level →
  computes difficulty window →
  checks word_bank.json for topics running low →
  generates new words via LLM →
  appends to word_bank.json
```

Protocol (described in SKILL.md):
1. Read `<data_path>/config.json` for `student_level`
2. Read `<data_path>/vocab/word_bank.json` — topics → word lists
3. Read `<data_path>/vocab/state.json` — words already in the learning pool
4. For each topic: if fewer than 5 unused words remain (in bank but not in state), generate new ones
5. Generated words must fall within the difficulty window derived from `student_level`
6. Append to the topic list in `word_bank.json`

Word format: `{"en": "...", "ru": "...", "difficulty": "A2-3"}`
Sublevel 1 = easiest within CEFR band, 5 = hardest.

## 7. Seed Format Update

`exercises/data/word_bank_seed.json` — update difficulty strings to include sublevels.
Mechanical replace: `"A1"` → `"A1-3"`, `"A2"` → `"A2-3"`, etc.
Midpoint (3) so LLM-generated words can spread across 1–5.

## 8. Files

| File | Action |
|---|---|
| `models.py` | Add `StudentLevel` frozen dataclass |
| `config.py` | Add `STUDENT_LEVEL` constant |
| `core/entry.py` | Write `config.json` at session start |
| `exercises/vocab.py` | Filtered seed copy + difficulty filter in `_replenish_pool` |
| `exercises/data/word_bank_seed.json` | Update difficulty strings with sublevels |
| `SKILL.md` | Add replenishment protocol section |
