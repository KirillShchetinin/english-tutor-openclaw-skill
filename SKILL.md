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

### Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `data_path` | `Path` | Yes | Directory for persisted learner state |
| `channel` | `OutputChannel \| None` | No | Override delivery channel (default: `TelegramChannel`) |
| `force` | `bool` | No | Skip guard checks (default: `False`) |

### `OutputChannel`

Any object that implements `async send(message: Message) -> None`. Each `Message` has:

| Field | Type | Description |
|---|---|---|
| `type` | `str` | Message category (e.g. `"vocab"`, `"grammar"`) |
| `content` | `str` | The message body |
| `parse_mode` | `str` | None | Optional formatting hint (e.g. `"HTML"`) |
