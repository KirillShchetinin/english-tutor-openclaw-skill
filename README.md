# English Tutor

An [OpenClaw](https://github.com/OpenClaw) Skill that delivers push-only English lessons to a beginner Russian-speaking learner. Sessions run 3x/day via cron or on-demand. All system-facing text is in Russian; English appears only inside exercise content.

## How It Works

Each session follows a fixed pipeline:

1. **Guard checks** — enforce a minimum gap between sessions and nudge inactive learners.
2. **Build** — assemble the exercise list from the registry.
3. **Execute** — run each exercise sequentially, sending output through a delivery channel.
4. **Persist** — save session state after completion (or partial progress on failure).

The default channel (`SkillChannel`) emits tagged lines to stdout for an LLM orchestrator to consume. A `ConsoleChannel` is available for local development.

## Project Structure

```
english-tutor/
├── config.py                  # Constants (timing, retries, pool sizes)
├── models.py                  # Pure dataclasses: Message, SessionState, UserProfile, etc.
├── core/
│   ├── entry.py               # run_session() — the single public API
│   ├── state.py               # JSON persistence (atomic writes)
│   ├── session_builder.py     # Builds exercise list from registry
│   └── session_executor.py    # Runs exercises with retry logic
├── exercises/
│   ├── base.py                # Exercise ABC and RunResult
│   ├── registry.py            # @register_exercise decorator, global registry
│   └── vocab.py               # Vocabulary exercise (word pool, spaced repetition)
├── channels/
│   ├── base.py                # OutputChannel ABC
│   ├── skill_channel.py       # Tagged stdout for LLM orchestrator
│   └── console.py             # Plain-text console output for dev/testing
└── tests/
    ├── run_session.py          # Manual test runner (python -m tests.run_session)
    ├── test_session.py
    ├── test_vocab.py
    └── test_models.py
```

## Quick Start

```bash
# Run tests
python -m pytest tests/ -v

# Run a test session locally (prints to console)
python -m tests.run_session --force
```

Without `--force`, guard checks (minimum session gap, absence nudge) apply.

## Adding a New Exercise

1. Create a class that extends `Exercise` in `exercises/`.
2. Implement the `name` property and `async run(channel, profile)` method.
3. Decorate with `@register_exercise`.
4. Import the module in `exercises/__init__.py` (triggers auto-discovery).

```python
from exercises.base import Exercise, RunResult
from exercises.registry import register_exercise

@register_exercise
class MyExercise(Exercise):
    @property
    def name(self) -> str:
        return "my_exercise"

    async def run(self, channel, profile) -> RunResult:
        await channel.send(Message(type="text", content="Hello!"))
        return RunResult(completed=True)
```

## Adding a New Channel

Implement `OutputChannel.send()` and optionally override `done()`, then pass the instance to `run_session(channel=...)`.

## Output Protocol

When using `SkillChannel`, only lines starting with `OClaw_SKILL|` are meaningful output. Format:

```
OClaw_SKILL|<invocation_id>|<json>
```

See [SKILL.md](SKILL.md) for the full protocol specification.
