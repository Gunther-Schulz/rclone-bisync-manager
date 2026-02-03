"""Tests for SyncStateStore and SyncState (load/save, job state)."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from rclone_bisync_manager.sync_state_store import SyncStateStore, SyncState


def test_sync_state_store_load_empty_dir(tmp_path: Path):
    """Load with no sync_state.json initializes empty state."""
    store = SyncStateStore(str(tmp_path))
    store.load()
    assert store.sync_state.last_sync_times == {}
    assert store.sync_state.sync_status == {}
    assert store.sync_state.get_job_state("any")["last_sync"] is None


def test_sync_state_store_save_and_load_roundtrip(tmp_path: Path):
    """Save then load preserves job state."""
    store = SyncStateStore(str(tmp_path))
    store.load()
    store.sync_state.update_job_state("job1", last_sync=datetime(2025, 1, 15, 12, 0), next_run=datetime(2025, 1, 15, 13, 0))
    store.sync_state.sync_status["job1"] = "COMPLETED"
    store.save()

    store2 = SyncStateStore(str(tmp_path))
    store2.load()
    assert store2.sync_state.last_sync_times["job1"] == datetime(2025, 1, 15, 12, 0)
    assert store2.sync_state.next_run_times["job1"] == datetime(2025, 1, 15, 13, 0)
    assert store2.sync_state.sync_status["job1"] == "COMPLETED"


def test_sync_state_store_load_invalid_json_falls_back_to_empty(tmp_path: Path):
    """Invalid sync_state.json initializes empty state."""
    state_file = tmp_path / "sync_state.json"
    state_file.write_text("not valid json {")
    store = SyncStateStore(str(tmp_path))
    store.load()
    assert store.sync_state.last_sync_times == {}


def test_sync_state_get_job_state_defaults():
    """get_job_state returns NONE for status when not set."""
    state = SyncState()
    state.update_job_state("j1", last_sync=datetime(2025, 1, 1))
    got = state.get_job_state("j1")
    assert got["last_sync"] == datetime(2025, 1, 1)
    assert got["sync_status"] == "NONE"
    assert got["resync_status"] == "NONE"
    assert got["next_run"] is None

    assert state.get_job_state("nonexistent")["last_sync"] is None
