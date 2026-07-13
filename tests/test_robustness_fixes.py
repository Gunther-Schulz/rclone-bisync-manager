"""Recovery-path fixes: path escape, stale locks, rclone's own log file."""

import argparse
import os
import textwrap

import pytest

from rclone_bisync_manager.config import Config
from rclone_bisync_manager.sync_context import rclone_log_path
from rclone_bisync_manager.utils import daemon_is_running


def _args():
    return argparse.Namespace(command="sync", sync_jobs=[], dry_run=False, console_log=False,
                              resync=[], force_resync=False, force_bisync=False,
                              force_operation=False)


def _load(tmp_path, local_value):
    (tmp_path / "data").mkdir(exist_ok=True)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(textwrap.dedent(f"""
        local_base_path: {tmp_path / "data"}
        sync_jobs:
          j1:
            local: {local_value}
            rclone_remote: r
            remote: some/path
            schedule: "0 0 * * *"
    """).lstrip())
    cfg = Config()
    cfg.set_config_file(str(cfg_file))
    cfg.load_and_validate_config(_args())
    return cfg


# --- A job must not sync a directory outside local_base_path --------------------------

def test_absolute_local_path_is_rejected(tmp_path):
    """os.path.join(base, "/etc") == "/etc": the base is silently discarded, and the daemon would
    then bisync /etc two-way against a remote."""
    with pytest.raises(Exception, match="absolute path"):
        _load(tmp_path, "/etc")


def test_parent_traversal_is_rejected(tmp_path):
    with pytest.raises(Exception, match="outside local_base_path"):
        _load(tmp_path, "../../etc")


def test_normal_relative_path_is_accepted(tmp_path):
    cfg = _load(tmp_path, "box")
    assert cfg._config.sync_jobs["j1"].local == "box"


def test_nested_relative_path_is_accepted(tmp_path):
    cfg = _load(tmp_path, "projects/box")
    assert cfg._config.sync_jobs["j1"].local == "projects/box"


# --- A stale lock file must not block manual syncs forever -----------------------------

def test_stale_lock_file_does_not_look_like_a_running_daemon(tmp_path, monkeypatch):
    """After a SIGKILL the lock file survives. Testing os.path.exists on it meant `sync` refused
    to run, permanently -- exactly when you needed a manual sync to recover."""
    lock = tmp_path / "daemon.lock"
    lock.write_text("999999")  # a PID that does not exist
    monkeypatch.setattr("rclone_bisync_manager.utils.get_lock_file_path", lambda: str(lock))
    assert daemon_is_running() is False


def test_missing_lock_file_means_no_daemon(tmp_path, monkeypatch):
    monkeypatch.setattr("rclone_bisync_manager.utils.get_lock_file_path",
                        lambda: str(tmp_path / "absent.lock"))
    assert daemon_is_running() is False


def test_garbage_lock_file_is_treated_as_stale(tmp_path, monkeypatch):
    lock = tmp_path / "daemon.lock"
    lock.write_text("")  # truncated, as the old one-off sync used to leave it
    monkeypatch.setattr("rclone_bisync_manager.utils.get_lock_file_path", lambda: str(lock))
    assert daemon_is_running() is False


def test_live_daemon_is_detected(tmp_path, monkeypatch):
    """Our own PID, with a matching cmdline, must read as a running daemon."""
    lock = tmp_path / "daemon.lock"
    lock.write_text(str(os.getpid()))
    monkeypatch.setattr("rclone_bisync_manager.utils.get_lock_file_path", lambda: str(lock))
    monkeypatch.setattr("rclone_bisync_manager.utils.psutil.Process",
                        lambda pid: type("P", (), {"cmdline": lambda self: ["rclone-bisync-manager", "daemon"]})())
    assert daemon_is_running() is True


# --- rclone logs to its own file, so daemon log rotation can't corrupt the offset -------

def test_rclone_log_is_a_separate_file_beside_the_daemon_log():
    daemon_log = "/var/log/rbm/rclone-bisync-manager.log"
    rclone = rclone_log_path(daemon_log)
    assert rclone != daemon_log
    assert os.path.dirname(rclone) == os.path.dirname(daemon_log)
    assert os.path.basename(rclone) == "rclone.log"
