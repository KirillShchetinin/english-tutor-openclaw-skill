---
name: english-tutor
description: "Teaches English to a beginner Russian-speaking adult through automated daily sessions. Runs 3x/day via cron or on-demand. Push-only lessons with vocabulary, grammar, and phrases."
metadata:
  version: "0.1"
---

# English Tutor

This skill delivers English lessons to a beginner Russian-speaking learner via Telegram. Sessions are push-only (no interactive quizzes in MVP). All system messages are in Russian; English appears only inside exercise content.

## Usage

```python
from english_tutor import run_session
await run_session(data_path)
```

Monitor stdout for lines starting with `OClaw_SKILL|` to get messages for the user. See "Output Protocol" below. **After session completes, follow "Post-Session Diagnostics" to check for exercise crashes and self-heal.**

### Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `data_path` | `Path` | Yes | Directory for persisted learner state |

## Output Protocol

When invoked with `SkillChannel`, the skill writes tagged lines to stdout. **Only lines starting with `OClaw_SKILL|` are messages for you. Ignore all other output.**

Format: `OClaw_SKILL|<invocation_id>|<json>`

- `invocation_id`: opaque identifier for this run. Ignore it.
- `json`: a JSON object with a `type` field.

### Message types

| `type` | Action |
|--------|--------|
| `done` | Session is complete. If `status` is `"ok"`, confirm to the user: "Урок завершён." If `status` is `"error"`, tell user: "Произошла ошибка, попробуй позже." |
| `text` | A message for the user. Send the `content` field as-is. Preserve formatting (Markdown/HTML per `parse_mode`). |

### Example output

```
OClaw_SKILL|a3f1b8c2|{"type":"text","content":"📖 **Словарный запас**\n\n1. **apple** — яблоко","parse_mode":"Markdown"}
OClaw_SKILL|a3f1b8c2|{"type":"done","status":"ok"}
```

### Error handling

| Situation | Action |
|---|---|
| Process exits without a `done` line | Session crashed. Tell user: "Урок завершился неожиданно. Попробуй позже." |
| Malformed JSON on a tagged line | Skip that line. Process remaining lines normally. |
| No tagged lines at all | Treat as error. Same as missing `done`. |

### Environment

Set `PYTHONIOENCODING=utf-8` when invoking the skill.

## Post-Session Diagnostics

After receiving `done`, scan stderr for `ERROR` lines **followed by a Python traceback** (`Traceback (most recent call last):`). A `done` with `status: "ok"` can still have silently skipped exercises. Ignore WARNING lines and ERROR lines without tracebacks — those are transient.

Example of an actionable error in stderr:
```
ERROR:core.session_executor:Exercise 'vocab' failed after 2 attempts, skipping.
Traceback (most recent call last):
  File "exercises/vocab.py", line 45, in run
    ...
KeyError: 'word'
```

**If you find a traceback**, spin up an Opus subagent with the full traceback and the skill source tree path. The subagent should:

1. Read the failing source file and line from the traceback.
2. Fix based on exception type:
   - `json.JSONDecodeError` / `RuntimeError("Corrupted…")` → fix or reset the data file under `<data_path>/<exercise>/` to `{}`.
   - `FileNotFoundError` → recreate missing file (state files as `{}`, seed files from `exercises/<name>/`).
   - `KeyError` on data dict → add missing keys with defaults.
   - `TypeError` / `AttributeError` / `IndexError` → code bug — apply a minimal fix.
3. Run `python -m pytest tests/ -v` to verify.

**Do not fix** `ConnectionError`, `TimeoutError` (transient), `PermissionError` (needs human), or `ImportError` (deployment issue). If uncertain — skip, do not guess.
