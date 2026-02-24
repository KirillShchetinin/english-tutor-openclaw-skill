"""
conftest.py — pytest configuration for english-tutor.

Redirects tmp_path to a local .tmp/ directory to avoid Windows
permission issues with the system temp directory.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_path(request) -> Path:
    """Override tmp_path to use a local .tmp/ directory."""
    base = Path(__file__).parent / ".tmp"
    base.mkdir(exist_ok=True)
    # Create a unique sub-directory per test
    test_name = request.node.name.replace("[", "_").replace("]", "_")
    tmp = base / test_name
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)
