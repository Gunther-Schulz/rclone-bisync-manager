"""dry_run must never be silently turned OFF: a user asking for a rehearsal must not get a
real, deleting bisync."""

import argparse
import textwrap

import pytest

from rclone_bisync_manager.config import Config
from rclone_bisync_manager.sync_context import build_sync_context


def _args(**overrides):
    base = dict(command="sync", sync_jobs=[], dry_run=False, console_log=False,
                resync=[], force_resync=False, force_bisync=False, force_operation=False)
    base.update(overrides)
    return argparse.Namespace(**base)


def _load(tmp_path, body, args=None):
    local = tmp_path / "data"
    local.mkdir(exist_ok=True)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(textwrap.dedent(body).format(local=local).lstrip())
    cfg = Config()
    cfg.set_config_file(str(cfg_file))
    cfg.load_and_validate_config(args or _args())
    return cfg


def test_config_dry_run_survives_a_command_without_the_flag(tmp_path):
    """`dry_run: true` in config.yaml used to be overwritten with False on every invocation
    that lacked -d, so the rehearsal ran for real."""
    cfg = _load(tmp_path, """
        local_base_path: {local}
        dry_run: true
        sync_jobs:
          j1:
            local: box
            rclone_remote: r
            remote: some/path
            schedule: "0 0 * * *"
    """, _args(dry_run=False))
    assert cfg._config.dry_run is True


def test_cli_flag_can_still_turn_dry_run_on(tmp_path):
    cfg = _load(tmp_path, """
        local_base_path: {local}
        sync_jobs:
          j1:
            local: box
            rclone_remote: r
            remote: some/path
            schedule: "0 0 * * *"
    """, _args(dry_run=True))
    assert cfg._config.dry_run is True


def test_per_job_dry_run_is_honored(tmp_path):
    """job.dry_run was defined, documented and offered in the config editor -- and read by
    nothing, so `dry_run: true` on a job ran a real bidirectional sync."""
    cfg = _load(tmp_path, """
        local_base_path: {local}
        sync_jobs:
          j1:
            local: box
            rclone_remote: r
            remote: some/path
            schedule: "0 0 * * *"
            dry_run: true
    """, _args(dry_run=False))
    assert cfg._config.dry_run is False  # global stays off
    assert build_sync_context("j1", cfg).dry_run is True  # the job's own setting wins


def test_force_bisync_only_applies_to_the_named_job(tmp_path):
    """`sync j1 --force-bisync` used to set force_operation on EVERY job in the config,
    disabling the --max-delete guard on all of them."""
    cfg = _load(tmp_path, """
        local_base_path: {local}
        sync_jobs:
          j1:
            local: box
            rclone_remote: r
            remote: some/path
            schedule: "0 0 * * *"
          j2:
            local: box2
            rclone_remote: r
            remote: other/path
            schedule: "0 0 * * *"
    """, _args(sync_jobs=["j1"], force_bisync=True))
    assert cfg._config.sync_jobs["j1"].force_operation is True
    assert cfg._config.sync_jobs["j2"].force_operation is False


def test_log_file_underscore_is_rejected(tmp_path):
    """Options are emitted as --{key with - for _}, so `log_file` reached rclone as
    --log-file and collided with the manager's own, while the guard only knew 'log-file'."""
    with pytest.raises(Exception, match="not allowed"):
        _load(tmp_path, """
            local_base_path: {local}
            rclone_options:
              log_file: /tmp/x
            sync_jobs:
              j1:
                local: box
                rclone_remote: r
                remote: some/path
                schedule: "0 0 * * *"
        """)
