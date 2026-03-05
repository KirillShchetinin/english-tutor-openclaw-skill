# Output Protocol — Details

> See [SKILL.md](../SKILL.md) for the core message types and done statuses.

## Example output

```
OClaw_SKILL|a3f1b8c2|{"type":"text","content":"📖 **Словарный запас**\n\n1. **apple** — яблоко","parse_mode":"Markdown"}
OClaw_SKILL|a3f1b8c2|{"type":"done","status":"ok"}
```

## Error handling

| Situation | Action |
|---|---|
| Process exits without a `done` line | Session crashed. Tell user: "Урок завершился неожиданно. Попробуй позже." |
| Malformed JSON on a tagged line | Skip that line. Process remaining lines normally. |
| No tagged lines at all | Treat as error. Same as missing `done`. |

## Environment

Set `PYTHONIOENCODING=utf-8` when invoking the skill.
