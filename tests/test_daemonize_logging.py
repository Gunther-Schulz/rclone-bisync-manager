"""Regression tests: daemonization must preserve the log file descriptor.

The daemon opens its RotatingFileHandler (setup_loggers) *before* entering
daemon.DaemonContext. python-daemon closes every inherited fd on daemonization
unless it is listed in files_preserve, so without it all post-fork logging is
written to a closed fd and silently lost. These tests pin that contract; an
in-process logging test alone never catches it because pytest never daemonizes.
"""

import logging
import types

import pytest

from rclone_bisync_manager import logging_utils
from rclone_bisync_manager.logging_utils import (
    log_files_to_preserve,
    set_config,
    setup_loggers,
)


@pytest.fixture
def file_logging(tmp_path):
    """Configure real file logging into a tmp dir; restore handlers afterward."""
    cfg = types.SimpleNamespace(
        log_file_path=str(tmp_path / "daemon.log"),
        console_log=False,
        log_rotation_max_mb=5,
        log_rotation_backup_count=5,
        min_console_level=logging.INFO,
    )
    set_config(cfg)
    setup_loggers(console_log=False)
    yield cfg
    logging_utils._stdlib_logger.handlers.clear()
    set_config(None)


def test_log_files_to_preserve_includes_log_file(file_logging):
    """The helper returns the open log file object, with a real descriptor."""
    preserved = log_files_to_preserve()
    assert preserved, "expected at least the RotatingFileHandler stream"
    assert all(isinstance(s.fileno(), int) and s.fileno() >= 0 for s in preserved)
    names = [getattr(s, "name", "") for s in preserved]
    assert any(str(n).endswith("daemon.log") for n in names)


def test_log_files_to_preserve_empty_without_file_logging():
    """No file handler configured -> nothing to preserve, no crash."""
    logging_utils._stdlib_logger.handlers.clear()
    set_config(None)
    assert log_files_to_preserve() == []


def test_run_daemon_start_passes_log_fd_to_daemoncontext(file_logging, monkeypatch):
    """run_daemon_start must hand the open log fd to DaemonContext(files_preserve=...)."""
    import rclone_bisync_manager.commands as commands

    captured = {}

    class FakeDaemonContext:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _StopBeforeRunLoop(Exception):
        pass

    # Don't really bootstrap, lock, daemonize, or run the loop.
    monkeypatch.setattr(commands.daemon, "DaemonContext", FakeDaemonContext)
    monkeypatch.setattr(commands, "_bootstrap_for_daemon", lambda *a, **k: None)
    monkeypatch.setattr(commands, "check_and_create_lock_file", lambda: (123, None))
    monkeypatch.setattr(commands, "SyncScheduler", lambda: object())
    monkeypatch.setattr(
        commands, "daemon_main", lambda: (_ for _ in ()).throw(_StopBeforeRunLoop())
    )

    args = types.SimpleNamespace(console_log=False)
    config_obj = types.SimpleNamespace(args=None)
    # run_daemon_start swallows the in-context exception and returns 1; we only
    # care that DaemonContext was constructed with files_preserve populated.
    commands.run_daemon_start(args, config_obj)

    assert "files_preserve" in captured, "DaemonContext called without files_preserve"
    preserved_fds = [s.fileno() for s in captured["files_preserve"]]
    handler_fds = [
        h.stream.fileno()
        for h in logging_utils._stdlib_logger.handlers
        if getattr(h, "stream", None) is not None
    ]
    assert handler_fds, "test setup should have produced a file handler"
    assert any(fd in preserved_fds for fd in handler_fds)
