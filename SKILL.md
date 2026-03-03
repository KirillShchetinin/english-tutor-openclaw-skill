---
name: english-tutor
description: "Teaches English to a beginner Russian-speaking adult through automated daily sessions. Runs 3x/day via cron or on-demand. Push-only lessons with vocabulary, grammar, and phrases."
metadata:
  version: "0.1"
---

# English Tutor

This skill delivers English lessons to a beginner Russian-speaking learner via Telegram. Sessions are push-only (no interactive quizzes in MVP). All system messages are in Russian; English appears only inside exercise content.

## Usage

### Starting a new session

```python
from english_tutor import run_session
await run_session(data_path)
```

Monitor stdout for lines starting with `OClaw_SKILL|` to get messages for the user. See "Output Protocol" below. **After session completes ('done' message), follow "Post-Session Diagnostics" to check for exercise crashes and self-heal.**

** if this skill is invoked by the cron job, it should first ask user if user wants to do the lesson now or later. If user wants to do it later, the skill should exit without doing anything. Otherwise, proceed with the lesson by making python call as outlined above.**

### Resuming after user reply

When a `done` message has `status: "reply"`, the session is **waiting for user input**. Deliver the exercise messages to the user and wait for their response. When the user replies, call `resume_session` with their input:

```python
from english_tutor import resume_session
await resume_session(data_path, user_input="the user's reply text")
```

`resume_session` feeds the user's answer to the waiting exercise, then continues with any remaining exercises. It emits the same tagged output protocol as `run_session` — including a final `done` message that may itself be `"reply"` (multi-turn exercises) or `"ok"` (session complete).

If there is no pending exercise (e.g. user sends a message without a waiting session), `resume_session` replies with a text message telling the user to start a new lesson.

### Parameters

**`run_session(data_path, channel=None, force=False)`**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `data_path` | `Path` | Yes | Directory for persisted learner state |
| `force` | `bool` | No | Skip guard checks (min session gap, absence nudge). Default `False`. |

**`resume_session(data_path, user_input, channel=None)`**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `data_path` | `Path` | Yes | Same directory used in `run_session` |
| `user_input` | `str` | Yes | The user's reply text |

## Output Protocol

When invoked with `SkillChannel`, the skill writes tagged lines to stdout. **Only lines starting with `OClaw_SKILL|` are messages for you. Ignore all other output.**

Format: `OClaw_SKILL|<invocation_id>|<json>`

- `invocation_id`: opaque identifier for this run. Ignore it.
- `json`: a JSON object with a `type` field.

### Message types

| `type` | Action |
|--------|--------|
| `done` | Session ended. Check `status` field — see **Done statuses** below. |
| `text` | A message for the user. Send the `content` field as-is. Preserve formatting (Markdown/HTML per `parse_mode`). |

### Done statuses

| `status` | Meaning | Action |
|----------|---------|--------|
| `"ok"` | Session completed normally. | Confirm to the user: "Урок завершён." |
| `"reply"` | An exercise is waiting for the user's answer. | Deliver the preceding `text` messages to the user, wait for their reply, then call `resume_session(data_path, user_input)`. |
| `"error"` | Session failed due to an internal error. The `error` field may contain details (e.g. `"internal_error"`). | Tell user: "Произошла ошибка, попробуй позже." |

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
