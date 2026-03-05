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
- `to_ordinal()` / `from_ordinal()` — flat integer for comparison; `from_ordinal()` raises `ValueError` if input not in [1, 30]
- Comparison operators via `@functools.total_ordering` (`__eq__` + `__lt__` using ordinals)
- `difficulty_window() -> tuple[StudentLevel, StudentLevel]`
- `__str__` → `"A2-3"`
- `parse()` validates: `cefr` must be one of the six known bands, `sublevel` must be 1–5. Raises `ValueError` with a descriptive message on invalid input.

### Difficulty Window Rule

The window includes the **full current CEFR band plus a 1-sublevel buffer on each side**, clamped to [1, 30].

Formula (single source of truth):
```
CEFR_BANDS = ["A1", "A2", "B1", "B2", "C1", "C2"]
band_index = CEFR_BANDS.index(cefr)       # 0–5
band_start = band_index * 5 + 1            # first ordinal of the band
band_end   = band_index * 5 + 5            # last ordinal of the band
low  = max(1,  band_start - 1)
high = min(30, band_end   + 1)
```

Window width: 7 for interior bands, 6 for A1 (clamped at bottom) and C2 (clamped at top). The student's sublevel within the band does not affect the window — only the band matters.

| Student Level | Band | band_start→band_end | low→high | Window |
|---|---|---|---|---|
| A2-2 | A2 | 6→10 | 5→11 | A1-5 → B1-1 |
| A1-3 | A1 | 1→5 | 1→6 | A1-1 → A2-1 |
| C2-4 | C2 | 26→30 | 25→30 | C1-5 → C2-5 |

## 3. Configuration

### Single source of truth: `<data_path>/config.json`

Written by **OpenClaw once**, before the first session ever runs. The skill reads it at runtime — never writes it.

```json
{
  "student_level": "A1-1"
}
```

**No Python constant in `config.py`.** The skill reads the level from `config.json` at the point of use (seed filtering, pool replenishment). A helper function in `config.py` provides access:

```python
def get_student_level() -> StudentLevel:
    """Read student_level from <data_path>/config.json. Raises if missing."""
    ...
```

If `config.json` or `student_level` key is missing, the function raises with a clear error message (the app cannot function without a configured level).

Difficulty window is computed at runtime — not stored.

### Level progression

Out of scope for this change. The level field in `config.json` can be updated manually or by a future automated mechanism. Words already in the active learning pool are not retroactively filtered on level change — they graduate naturally. New words pulled from the bank will be filtered by the updated window.

## 4. Seed → Word Bank: Filtered Copy

Currently `_load_state()` does a blind `shutil.copy2(seed, word_bank.json)` on first run.

Change: load the seed JSON, filter each topic's words by the difficulty window, write the filtered result. The bank starts with only level-appropriate words from day one.

```
seed (all levels, A1–C2)
  → filter by difficulty_window(get_student_level())
  → write word_bank.json (only level-appropriate words)
```

**Empty bank guard:** If filtering produces zero words across all topics, raise a specific error with a clear message (e.g., `"Filtered word bank is empty — student level {level} has no matching words in the seed. Check config.json."`) both logged and surfaced to the user. The app is broken and must not silently continue.

## 5. Difficulty Filtering in `_replenish_pool`

Belt-and-suspenders check for words OpenClaw adds later that might be slightly off-range:

```python
level = get_student_level()
low, high = level.difficulty_window()
...
try:
    word_level = StudentLevel.parse(word["difficulty"])
except (ValueError, KeyError):
    continue  # skip malformed entries
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
Use regex replacement with word-boundary awareness (e.g., `re.sub(r'"(A1|A2|B1|B2|C1|C2)"', r'"\1-3"', text)`) — not naive `str.replace` which would corrupt `"B1"` inside other strings.
Midpoint (3) so LLM-generated words can spread across 1–5.

## 8. Files

| File | Action |
|---|---|
| `models.py` | Add `StudentLevel` frozen dataclass |
| `config.py` | Add `get_student_level()` that reads from `config.json` |
| `exercises/vocab.py` | Filtered seed copy + difficulty filter in `_replenish_pool` |
| `exercises/data/word_bank_seed.json` | Update difficulty strings with sublevels |
| `SKILL.md` | Add replenishment protocol section |

Note: `core/entry.py` is **not** modified — `config.json` is owned and written by OpenClaw, not by the skill.
