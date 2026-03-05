"""
conftest.py — pytest configuration for english-tutor.

Redirects tmp_path to a local .tmp/ directory to avoid Windows
permission issues with the system temp directory.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_path(request) -> Path:
    """Override tmp_path to use a local .tmp/ directory.

    Also writes a default config.json with student_level=A1-1 so that
    any test that exercises vocab functionality doesn't need to set it up
    manually. Tests that need a different level can overwrite the file.
    """
    base = Path(__file__).parent / ".tmp"
    base.mkdir(exist_ok=True)
    # Create a unique sub-directory per test; sanitize all path-unsafe chars.
    test_name = re.sub(r'[^\w\-]', '_', request.node.name)
    tmp = base / test_name
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    (tmp / "config.json").write_text(
        json.dumps({"student_level": "A1-1"}), encoding="utf-8"
    )
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)
