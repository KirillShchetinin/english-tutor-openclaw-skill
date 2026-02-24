# English Tutor — Skill Design Summary

**Project:** English Tutor Telegram Bot for a beginner Russian-speaking adult
**Platform:** OpenClaw (Telegram bot + Claude API)

---

## Overview

A Telegram bot skill that teaches English through automated daily sessions — 3x/day via cron, or on-demand ("давай заниматься"). Push-only in MVP (no interactive quizzes).

## Architecture

Clean three-stage pipeline:

- **`core/entry.py`** — `run_session()` orchestrates the pipeline: loads state, runs guard checks, delegates to builder and executor, updates state.
- **`core/session_builder.py`** — `build_session(session_state, user_profile) → list[Exercise]` — the single point for sequencing and scheduling logic.
- **`core/session_executor.py`** — Generic loop. Iterates exercises, calls `get_content()`, sends messages to Telegram. Knows nothing about exercise types.

All external I/O (LLM calls, Telegram sends) is wrapped in async awaitable functions. The pipeline runs async.

All system messages (skip notifications, nudges, error messages to user, session summaries) are in Russian. English only appears inside exercise content.

## Exercise Interface

Every exercise implements one method:

```python
get_content(user_profile) → list[Message]
```

Where `Message` is:

```python
{
    "type":       "text" | "voice" | "image",
    "content":    str,       # text body or file path
    "parse_mode": "markdown" | "html" | None
}
```

Each exercise is fully self-contained — loads its own data, manages its own state files, calls LLM if needed. Knows nothing about other exercises or its position in the session.

Adding a new exercise: implement the interface, register in `session_builder.py`. No changes to executor, entry point, or other exercises.

Future interactivity extends the interface with an `evaluate()` method without changing the core pipeline.

## State

JSON files in `<workspace>/data/skills/english-tutor/` with strict ownership boundaries.

### Framework State

| File | Owner | Access |
|---|---|---|
| `session_state.json` | `entry.py` | `entry.py` only |
| `user_profile.json` | `entry.py` | `entry.py` writes; exercises receive as parameter |

**session_state.json** — `sessions_completed`, `last_completed_at`, `sessions_skipped`.

**user_profile.json** — LLM-generated learner summary, metrics (words learned/in-progress counts, accuracy, streak), weak spots, strong topics. No actual vocabulary words — those live in exercise-owned state. Refreshed via LLM every 5th session.

### Exercise State

Each exercise creates and manages its own files in the same directory. Framework never touches them. Exercises never touch each other's state.

## Guard Logic (`entry.py`)

- **< 1 hour since last session** → send message that session is skipped (too soon), exit
- **2+ days absent** → send gentle nudge, skip full session
- **Normal gap** → run session

Spaced repetition timers pause on absence — words are not penalized.

## Testing Mode

Invoked via `--test` flag on entry point. Optionally `--force` to skip all guard checks.

Three changes, zero exercise modifications:

**1. Output backend abstraction.** `SessionExecutor` takes a backend that implements `send(message)`. Production backend sends to Telegram. Test backend prints to console. Exercises are unaware — they return messages, executor routes them.

**2. State isolation.** `--test` swaps the data path to a `test_state/` subdirectory. Exercises inherit the path, so all state (framework and exercise-owned) lands in isolation.

```
<workspace>/data/skills/english-tutor/
├── session_state.json          ← production
├── user_profile.json           ← production
└── test_state/
    ├── session_state.json      ← test
    └── user_profile.json       ← test
    └── ...                     ← exercise test state
```

**3. Transcript generation.** After session completes, test mode writes a markdown transcript to `<skill_dir>/tests/session_<timestamp>.md` — full message sequence grouped by exercise, with message counts.

**`--force` flag.** Skips guard checks (min gap, absence). Allows back-to-back runs during development.

## Error Handling

Each step of `run_session()` and its failure modes:

**Load state files.** Missing → create with defaults. Corrupted → abort session, raise error. No fallback, no guessing.

**Guard checks.** Pure logic. No failure path.

**`build_session()`.** Pure function. No failure path.

**`get_content()` per exercise.** LLM timeouts, bad response format, file I/O errors. On failure → one retry. Retry fails → log error, skip exercise, continue to next.

**Send to Telegram (agent message).** On connection failure → retry after a few seconds. Any other failure → log error, move on.

**Update state.** State is written per-exercise, not per-session. After each exercise completes and its Telegram send succeeds, write to `session_state.json` immediately. `session_state.json` tracks per-exercise completion (exercise type + timestamp), so on crash mid-session, next run resumes from where it left off. No duplicates.

**Profile refresh.** LLM may return malformed JSON. Validate response against expected schema. If invalid, send back to LLM to fix. Loop until validation passes or 5 minute timeout. On timeout → keep old profile, log error. On success → write.

## Configuration

All tuneable constants in one place:

| Constant | Default | Purpose |
|---|---|---|
| `WORKSPACE_DATA_PATH` | `<workspace>/data/skills/english-tutor/` | State directory |
| `SESSION_PUSH_TIMES` | `[9:00, 14:00, 20:00]` | Cron schedule |
| `MIN_SESSION_GAP_HOURS` | `1` | Prevent double-firing |
| `ABSENCE_NUDGE_DAYS` | `2` | Days idle before nudge |
| `PROFILE_REFRESH_INTERVAL` | `5` | Sessions between LLM profile refresh |

Exercise-specific constants live inside each exercise module.
