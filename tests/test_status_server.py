"""Tests for status_server: standardize_status, generate_status_report."""

import json
from pathlib import Path

import pytest

from rclone_bisync_manager import status_protocol as sp
from rclone_bisync_manager.config import ConfigSchema
from rclone_bisync_manager.status_server import standardize_status, generate_status_report
from rclone_bisync_manager.sync_state_store import SyncStateStore


def test_standardize_status_none():
    assert standardize_status(None) == "NONE"


def test_standardize_status_str():
    assert standardize_status("COMPLETED") == "COMPLETED"
    assert standardize_status("FAILED") == "FAILED"


def test_standardize_status_dict():
    assert standardize_status({"x": "COMPLETED"}) == "COMPLETED"
    assert standardize_status({"x": "NONE", "y": "FAILED"}) == "FAILED"
    assert standardize_status({"x": "NONE"}) == "NONE"
    assert standardize_status({}) == "NONE"


def test_generate_status_report_has_version_pid_running(tmp_path: Path, monkeypatch):
    """generate_status_report returns JSON with version, pid, running."""
    store = SyncStateStore(str(tmp_path))
    store.load()
    monkeypatch.setattr("rclone_bisync_manager.status_server.get_sync_state_store", lambda: store)

    class State:
        running = True
        shutting_down = False
        currently_syncing = None
        queued_paths = set()

    class Config:
        config_file = "/tmp/config.yaml"
        config_changed_on_disk = False
        _config = None

    raw = generate_status_report(state=State(), config=Config())
    data = json.loads(raw)
    assert "version" in data
    assert data.get("version") is not None
    assert "pid" in data
    assert isinstance(data["pid"], int)
    assert data["running"] is True
    assert "sync_errors" in data


def test_generate_status_report_config_valid_includes_sync_jobs(tmp_path: Path, monkeypatch):
    """When config is valid (not limbo, not invalid), response includes sync_jobs with per-job state."""
    store = SyncStateStore(str(tmp_path))
    store.load()
    monkeypatch.setattr("rclone_bisync_manager.status_server.get_sync_state_store", lambda: store)

    config_schema = ConfigSchema(
        local_base_path=str(tmp_path),
        sync_jobs={
            "job1": {
                "local": "subdir",
                "rclone_remote": "remote",
                "remote": "path/on/remote",
                "schedule": "0 * * * *",
                "active": True,
            }
        },
    )

    class State:
        running = True
        shutting_down = False
        currently_syncing = None
        queued_paths = set()
        in_limbo = False
        config_invalid = False

    class Config:
        config_file = "/tmp/config.yaml"
        config_changed_on_disk = False
        _config = config_schema
        hash_warnings = {}

    raw = generate_status_report(state=State(), config=Config())
    data = json.loads(raw)
    assert sp.SYNC_JOBS in data
    sync_jobs = data[sp.SYNC_JOBS]
    assert isinstance(sync_jobs, dict)
    assert "job1" in sync_jobs
    job1 = sync_jobs["job1"]
    assert sp.LAST_SYNC in job1
    assert sp.NEXT_RUN in job1
    assert sp.SYNC_STATUS in job1
    assert sp.RESYNC_STATUS in job1
    assert sp.HASH_WARNINGS in job1
    assert job1[sp.SYNC_STATUS] == "NONE"
    assert job1[sp.RESYNC_STATUS] == "NONE"
