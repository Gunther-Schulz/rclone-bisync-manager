"""Tests for utils: calculate_md5."""

from pathlib import Path

import pytest

from rclone_bisync_manager.utils import calculate_md5


def test_calculate_md5_known_value(tmp_path: Path):
    """calculate_md5 returns correct hex digest for file content."""
    f = tmp_path / "f"
    f.write_bytes(b"hello\n")
    assert calculate_md5(str(f)) == "b1946ac92492d2347c6235b4d2611184"


def test_calculate_md5_empty_file(tmp_path: Path):
    """calculate_md5 for empty file."""
    f = tmp_path / "empty"
    f.write_bytes(b"")
    assert calculate_md5(str(f)) == "d41d8cd98f00b204e9800998ecf8427e"
