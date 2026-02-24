"""
Test runner for english-tutor sessions.

Usage from the english-tutor directory:
    python -m tests.run_session --force
    python -m tests.run_session
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from channels.console import ConsoleChannel
from core.entry import run_session
from core.state import load_state

TESTS_DIR = Path(__file__).parent
DATA_DIR = TESTS_DIR / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description="English Tutor test session runner")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip guard checks (min gap, absence)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    channel = ConsoleChannel()
    asyncio.run(run_session(DATA_DIR, channel=channel, force=args.force))
    _write_transcript()


def _write_transcript() -> None:
    """Write a markdown transcript of the session to tests/data/ directory."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    transcript_path = DATA_DIR / f"session_{timestamp}.md"

    state = load_state(DATA_DIR)

    lines = [
        f"# Session Transcript -- {timestamp}",
        "",
        f"**Sessions completed:** {state.sessions_completed}",
        f"**Exercise completions this run:** {len(state.exercise_completions)}",
        "",
        "---",
        "",
        "_Transcript generated in test mode._",
    ]

    transcript_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nTranscript written to: {transcript_path}")


if __name__ == "__main__":
    main()
