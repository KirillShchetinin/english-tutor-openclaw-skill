# Word Bank Replenishment Protocol

The word bank is the inventory of English vocabulary available to exercises. After each session completes (after the `done` message is emitted), the word bank should be replenished if any topic is running low on unused words.

## When

Immediately after `run_session` or `resume_session` completes with a `done` message of any status. Replenishment is independent of session success or failure — if topics are depleted, refill them.

## How

**1. Read the student level**

```python
import json
config_path = data_path / "config.json"
config = json.loads(config_path.read_text())
student_level = config["student_level"]  # e.g. "A1-1"
```

**2. Compute the difficulty window**

Extract the CEFR band and sublevel from `student_level`:
- Band: A1, A2, B1, B2, C1, C2
- Sublevel: 1–5 (1 = easiest, 5 = hardest)

Compute the window as: **full CEFR band + 1 sublevel buffer on each side**, clamped to [A1-1, C2-5].

The window spans the full CEFR band (all 5 sublevels) plus 1 sublevel below and 1 sublevel above, clamped to [A1-1, C2-5]. Note: the buffer is always exactly 1 sublevel regardless of the student's sublevel within the band.

Example:
- Student level A1-1 → band A1 (ordinals 1–5). Low = max(1, 1-1) = 1 → A1-1. High = min(30, 5+1) = 6 → A2-1. Window: A1-1 to A2-1.
- Student level B1-3 → band B1 (ordinals 11–15). Low = max(1, 11-1) = 10 → A2-5. High = min(30, 15+1) = 16 → B2-1. Window: A2-5 to B2-1.
- Student level C2-5 → band C2 (ordinals 26–30). Low = max(1, 26-1) = 25 → C1-5. High = min(30, 30+1) = 30 → C2-5. Window: C1-5 to C2-5.

**3. Read the word bank and learning state**

```python
word_bank_path = data_path / "vocab" / "word_bank.json"
word_bank = json.loads(word_bank_path.read_text()) if word_bank_path.exists() else {}

state_path = data_path / "vocab" / "state.json"
state = json.loads(state_path.read_text()) if state_path.exists() else {}
```

**4. Check topic inventory and replenish**

`state.json` is a flat dict keyed by English word. Each value tracks the word's learning progress (see "State Format" below). A word from the word bank is "used" if it appears as a key in `state.json`, regardless of its learning status.

For each topic in the word bank:

1. Get the list of words in that topic: `topic_words = word_bank.get(topic, [])`
2. Get the set of all words already in state: `used_words = set(state.keys())`
3. Count unused words: `unused = [w for w in topic_words if w["en"] not in used_words]`
4. If `len(unused) < 5`, generate new words to bring the total to 5 unused words

**5. Generate new words**

If a topic needs replenishment:

1. Determine how many words to generate: `needed = 5 - len(unused)`
2. Generate `needed` words, each with structure: `{"en": "...", "ru": "...", "difficulty": "CEFR-sublevel"}`
3. All generated words must have `difficulty` within the computed window (step 2)
4. Append the new words to the topic list in `word_bank.json`

## Word Format

Each word in `word_bank.json` topics is a JSON object:

```json
{
  "en": "apple",
  "ru": "яблоко",
  "difficulty": "A1-1"
}
```

- `en`: English word (lowercase, singular unless plural is standard)
- `ru`: Russian translation
- `difficulty`: CEFR level with sublevel (e.g. `"A1-1"`, `"B1-3"`, `"C2-5"`)

## Config Ownership

`<data_path>/config.json` is written once by OpenClaw before the first session and is **read-only** from the skill's perspective. The skill must never modify it.

## Example State Files

**word_bank.json** (topic → word list):
```json
{
  "fruits": [
    {"en": "apple", "ru": "яблоко", "difficulty": "A1-1"},
    {"en": "orange", "ru": "апельсин", "difficulty": "A1-2"}
  ],
  "colors": [
    {"en": "red", "ru": "красный", "difficulty": "A1-1"}
  ]
}
```

**state.json** (English word → learning entry):
```json
{
  "apple": {
    "en": "apple",
    "ru": "яблоко",
    "topic": "fruits",
    "difficulty": "A1-1",
    "is_learning": true,
    "times_shown": 3,
    "times_tested": 0,
    "results": [],
    "last_seen": "2026-03-05T10:00:00+00:00"
  },
  "orange": {
    "en": "orange",
    "ru": "апельсин",
    "topic": "fruits",
    "difficulty": "A1-2",
    "is_learning": false,
    "times_shown": 8,
    "times_tested": 0,
    "results": [],
    "last_seen": "2026-03-04T18:00:00+00:00"
  },
  "red": {
    "en": "red",
    "ru": "красный",
    "topic": "colors",
    "difficulty": "A1-1",
    "is_learning": false,
    "times_shown": 10,
    "times_tested": 0,
    "results": [],
    "last_seen": "2026-03-04T14:00:00+00:00"
  }
}
```

## State Format

Each entry in `state.json` is keyed by the English word and contains:

| Field | Type | Description |
|---|---|---|
| `en` | `str` | English word |
| `ru` | `str` | Russian translation |
| `topic` | `str` | Which topic this word belongs to |
| `difficulty` | `str` | CEFR level with sublevel (e.g. `"A1-1"`) |
| `is_learning` | `bool` | `true` if actively being taught, `false` if graduated |
| `times_shown` | `int` | Number of times the word has been shown to the student |
| `times_tested` | `int` | Number of times the word has been tested |
| `results` | `list` | Test results history |
| `last_seen` | `str\|null` | ISO 8601 timestamp of last presentation, or `null` if never shown |

A word graduates from learning (`is_learning` becomes `false`) after being shown 8 times. Both learning and graduated words are "used" -- any word present as a key in state.json will not be drawn from the word bank again.

In the example above, "fruits" has 2 words in state (apple and orange), so if the word bank has only those 2 fruits, all are used and 5 new fruit words are needed. "colors" has 1 word in state (red), so if the word bank also has only that 1 color word, all are used and 5 new color words are needed.
