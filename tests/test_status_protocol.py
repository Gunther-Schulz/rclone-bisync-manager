"""Tests for status_protocol: _has_sync_issues, status_to_display_state."""

from rclone_bisync_manager import status_protocol as sp
from rclone_bisync_manager.status_protocol import (
    _has_sync_issues,
    status_to_display_state,
    DaemonState,
)


def test_has_sync_issues_none_or_not_dict():
    assert _has_sync_issues(None) is False
    assert _has_sync_issues("x") is False


def test_has_sync_issues_no_jobs_no_errors():
    assert _has_sync_issues({}) is False
    assert _has_sync_issues({sp.SYNC_JOBS: {}}) is False


def test_has_sync_issues_job_completed_no_issues():
    status = {
        sp.SYNC_JOBS: {
            "j1": {sp.SYNC_STATUS: "COMPLETED", sp.RESYNC_STATUS: "NONE", sp.HASH_WARNINGS: False},
        }
    }
    assert _has_sync_issues(status) is False


def test_has_sync_issues_job_failed():
    status = {
        sp.SYNC_JOBS: {
            "j1": {sp.SYNC_STATUS: "FAILED", sp.RESYNC_STATUS: "NONE", sp.HASH_WARNINGS: False},
        }
    }
    assert _has_sync_issues(status) is True


def test_has_sync_issues_hash_warnings():
    status = {
        sp.SYNC_JOBS: {
            "j1": {sp.SYNC_STATUS: "COMPLETED", sp.RESYNC_STATUS: "NONE", sp.HASH_WARNINGS: True},
        }
    }
    assert _has_sync_issues(status) is True


def test_has_sync_issues_sync_errors_dict():
    assert _has_sync_issues({sp.SYNC_ERRORS: {"path": {}}}) is True
    assert _has_sync_issues({sp.SYNC_ERRORS: {}}) is False


def test_status_to_display_state_daemon_start_error():
    assert status_to_display_state({}, daemon_start_error="x") == DaemonState.FAILED


def test_status_to_display_state_offline():
    assert status_to_display_state(None) == DaemonState.OFFLINE
    assert status_to_display_state({}) == DaemonState.OFFLINE


def test_status_to_display_state_running():
    assert status_to_display_state({sp.RUNNING: True, sp.CURRENTLY_SYNCING: None}) == DaemonState.RUNNING


def test_status_to_display_state_syncing():
    assert status_to_display_state({sp.RUNNING: True, sp.CURRENTLY_SYNCING: "job1"}) == DaemonState.SYNCING


def test_status_to_display_state_limbo():
    assert status_to_display_state({sp.RUNNING: True, sp.IN_LIMBO: True}) == DaemonState.LIMBO


def test_status_to_display_state_config_invalid():
    assert status_to_display_state({sp.RUNNING: True, sp.CONFIG_INVALID: True}) == DaemonState.CONFIG_INVALID


def test_status_to_display_state_error_response():
    assert status_to_display_state({sp.STATUS: "error"}) == DaemonState.FAILED
    assert status_to_display_state({sp.ERROR: "msg"}) == DaemonState.FAILED
