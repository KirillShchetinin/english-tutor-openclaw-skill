# Post-Session Diagnostics

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
