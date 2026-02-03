"""Tests for runtime_paths: path suffixes, write/read/clear crash log."""

from pathlib import Path

import pytest

from rclone_bisync_manager import runtime_paths


def test_runtime_path_suffixes():
    """Path helpers return strings ending with expected basenames."""
    assert runtime_paths.get_status_socket_path().endswith("rclone_bisync_manager_status.sock")
    assert runtime_paths.get_add_sync_socket_path().endswith("rclone_bisync_manager_add_sync.sock")
    assert runtime_paths.get_lock_file_path().endswith("rclone_bisync_manager.lock")
    assert runtime_paths.get_crash_log_path().endswith("rclone_bisync_manager_crash.log")


def test_write_read_clear_crash_log(tmp_path: Path, monkeypatch):
    """write_crash_log, read_crash_log, clear_crash_log with temp path."""
    crash_path = tmp_path / "crash.log"
    monkeypatch.setattr(runtime_paths, "get_crash_log_path", lambda: str(crash_path))

    assert runtime_paths.read_crash_log() is None
    runtime_paths.write_crash_log("error message")
    assert runtime_paths.read_crash_log() == "error message"
    assert runtime_paths.clear_crash_log() is True
    assert runtime_paths.read_crash_log() is None
    assert runtime_paths.clear_crash_log() is False
