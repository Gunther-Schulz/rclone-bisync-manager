"""Tests for sync: handle_rclone_exit_code return and error recording."""

from pathlib import Path

import pytest

from rclone_bisync_manager.sync import handle_rclone_exit_code
from rclone_bisync_manager.sync_state_store import SyncStateStore


def test_handle_rclone_exit_code_0_returns_completed(tmp_path: Path, monkeypatch):
    """Exit code 0 returns COMPLETED and clears sync error."""
    store = SyncStateStore(str(tmp_path))
    store.load()
    store.update_sync_error("/path", "Bisync", 1, "old")
    monkeypatch.setattr("rclone_bisync_manager.sync.get_sync_state_store", lambda: store)

    result = handle_rclone_exit_code(0, "/path", "Bisync")
    assert result == "COMPLETED"
    assert "/path" not in store.sync_errors


def test_handle_rclone_exit_code_9_returns_completed(tmp_path: Path, monkeypatch):
    """Exit code 9 (no transfer) returns COMPLETED."""
    store = SyncStateStore(str(tmp_path))
    store.load()
    monkeypatch.setattr("rclone_bisync_manager.sync.get_sync_state_store", lambda: store)

    result = handle_rclone_exit_code(9, "/path", "Resync")
    assert result == "COMPLETED"


def test_handle_rclone_exit_code_nonzero_returns_failed_and_records_error(tmp_path: Path, monkeypatch):
    """Non-zero exit (except 9) returns FAILED and records sync error."""
    store = SyncStateStore(str(tmp_path))
    store.load()
    monkeypatch.setattr("rclone_bisync_manager.sync.get_sync_state_store", lambda: store)

    result = handle_rclone_exit_code(1, "/local/path", "Bisync")
    assert result == "FAILED"
    assert "/local/path" in store.sync_errors
    assert store.sync_errors["/local/path"]["sync_type"] == "Bisync"
    assert store.sync_errors["/local/path"]["error_code"] == 1


def test_handle_rclone_exit_code_unknown_code_returns_failed(tmp_path: Path, monkeypatch):
    """Unknown exit code returns FAILED with message."""
    store = SyncStateStore(str(tmp_path))
    store.load()
    monkeypatch.setattr("rclone_bisync_manager.sync.get_sync_state_store", lambda: store)

    result = handle_rclone_exit_code(99, "/path", "Bisync")
    assert result == "FAILED"
    assert "unknown" in store.sync_errors["/path"]["message"].lower()
