"""Tests for status_server: standardize_status, generate_status_report."""
import os

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


def test_shutdown_during_a_request_logs_no_error(tmp_path, monkeypatch):
    """Stopping the server while a client request is in flight (the tray polls STATUS every few
    seconds) must not log 'Error handling client request: Bad file descriptor': the daemon is
    exiting, nothing failed, and an ERROR line on a non-defect trains people to ignore the log."""
    import socket
    import threading
    import time
    from types import SimpleNamespace
    from rclone_bisync_manager import status_server, config as config_mod

    sock_path = str(tmp_path / "s.sock")
    monkeypatch.setattr(status_server, "get_status_socket_path", lambda: sock_path)
    monkeypatch.setattr(config_mod, "get_config", lambda: SimpleNamespace())
    in_handler = threading.Event()

    def slow_report(s, c):
        in_handler.set()
        time.sleep(1.5)          # the server loop ends (1 s accept timeout) while we are here
        return json.dumps({"status": "ok"})

    monkeypatch.setattr(status_server, "generate_status_report", slow_report)
    errors = []
    monkeypatch.setattr(status_server, "log_error", lambda msg: errors.append(msg))

    state = SimpleNamespace(running=True, shutdown_complete=False, shutting_down=False)
    server = threading.Thread(target=status_server.start_status_server, kwargs={"state": state})
    server.start()
    for _ in range(100):
        if os.path.exists(sock_path):
            break
        time.sleep(0.02)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(sock_path)
    client.sendall(b"STATUS")
    assert in_handler.wait(2)
    state.running, state.shutting_down, state.shutdown_complete = False, True, True
    server.join(5)
    time.sleep(1.0)              # let the handler thread finish its sendall
    client.close()
    assert not server.is_alive()
    assert errors == [], errors


def test_request_outliving_the_shutdown_drain_logs_no_error(tmp_path, monkeypatch):
    """A handler still running after HANDLER_DRAIN_SECONDS finds its connection shut down; that
    is the shutdown working, not a failure."""
    import socket
    import threading
    import time
    from types import SimpleNamespace
    from rclone_bisync_manager import status_server, config as config_mod

    sock_path = str(tmp_path / "s.sock")
    monkeypatch.setattr(status_server, "get_status_socket_path", lambda: sock_path)
    monkeypatch.setattr(config_mod, "get_config", lambda: SimpleNamespace())
    monkeypatch.setattr(status_server, "HANDLER_DRAIN_SECONDS", 0.1)
    in_handler = threading.Event()

    def slow_report(s, c):
        in_handler.set()
        time.sleep(1.5)
        return json.dumps({"status": "ok"})

    monkeypatch.setattr(status_server, "generate_status_report", slow_report)
    errors = []
    monkeypatch.setattr(status_server, "log_error", lambda msg: errors.append(msg))
    state = SimpleNamespace(running=True, shutdown_complete=False, shutting_down=False)
    server = threading.Thread(target=status_server.start_status_server, kwargs={"state": state})
    server.start()
    for _ in range(100):
        if os.path.exists(sock_path):
            break
        time.sleep(0.02)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(sock_path)
    client.sendall(b"STATUS")
    assert in_handler.wait(2)
    state.running, state.shutting_down, state.shutdown_complete = False, True, True
    server.join(5)
    time.sleep(1.5)
    client.close()
    assert errors == [], errors
