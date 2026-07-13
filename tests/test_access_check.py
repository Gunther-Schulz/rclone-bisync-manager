"""Tests for the --check-access marker pre-flight: opt-in, and exact-match."""

import pytest

from rclone_bisync_manager.subprocess_executor import check_access_marker
from rclone_bisync_manager.sync import resolve_access_check


class FakeJob:
    def __init__(self, rclone_options=None, bisync_options=None, resync_options=None):
        self.rclone_options = rclone_options or {}
        self.bisync_options = bisync_options or {}
        self.resync_options = resync_options or {}


class FakeContext:
    def __init__(self, rclone_options=None, bisync_options=None, resync_options=None, job=None):
        self.rclone_options = rclone_options or {}
        self.bisync_options = bisync_options or {}
        self.resync_options = resync_options or {}
        self.job = job or FakeJob()


@pytest.fixture
def marker_name(monkeypatch):
    """Pin the configured marker filename without loading a real config."""
    class FakeConfig:
        rclone_test_file_name = "RCLONE_TEST"

    monkeypatch.setattr("rclone_bisync_manager.config.get_config", lambda: FakeConfig())
    return "RCLONE_TEST"


def test_check_disabled_when_check_access_absent(marker_name):
    """The default: no check_access in config means no marker is required."""
    enabled, _ = resolve_access_check(FakeContext())
    assert enabled is False


def test_check_enabled_by_yaml_null(marker_name):
    """`check_access:` with no value is YAML null, meaning "pass the bare flag"."""
    enabled, filename = resolve_access_check(FakeContext(rclone_options={"check_access": None}))
    assert enabled is True
    assert filename == "RCLONE_TEST"


def test_check_enabled_by_true(marker_name):
    enabled, _ = resolve_access_check(FakeContext(rclone_options={"check_access": True}))
    assert enabled is True


def test_check_disabled_by_explicit_false(marker_name):
    enabled, _ = resolve_access_check(FakeContext(rclone_options={"check_access": False}))
    assert enabled is False


def test_check_enabled_per_job(marker_name):
    """A job can opt in even when the global options don't."""
    enabled, _ = resolve_access_check(FakeContext(job=FakeJob({"check_access": None})))
    assert enabled is True


def test_custom_marker_filename_is_honored(marker_name):
    """rclone's --check-filename renames the marker; we must look for the same name."""
    _, filename = resolve_access_check(
        FakeContext(rclone_options={"check_access": None, "check_filename": "MY_MARKER"})
    )
    assert filename == "MY_MARKER"


def test_marker_present_returns_no_reason(monkeypatch):
    monkeypatch.setattr(
        "rclone_bisync_manager.subprocess_executor.check_command_output",
        lambda command: (True, "RCLONE_TEST\nnotes.txt\nsubdir/\n", ""),
    )
    assert check_access_marker("/data/sync", "RCLONE_TEST") is None


def test_marker_missing_reason_names_the_fix(monkeypatch):
    monkeypatch.setattr(
        "rclone_bisync_manager.subprocess_executor.check_command_output",
        lambda command: (True, "notes.txt\n", ""),
    )
    reason = check_access_marker("/data/sync", "RCLONE_TEST")
    assert reason is not None
    assert "RCLONE_TEST" in reason
    assert 'rclone touch "/data/sync/RCLONE_TEST"' in reason


def test_marker_match_is_exact_not_substring(monkeypatch):
    """A file merely containing the marker name must not satisfy the check."""
    monkeypatch.setattr(
        "rclone_bisync_manager.subprocess_executor.check_command_output",
        lambda command: (True, "RCLONE_TESTING.txt\n", ""),
    )
    assert check_access_marker("/data/sync", "RCLONE_TEST") is not None


def test_unreachable_path_reports_rclone_error(monkeypatch):
    """An unreachable path is a different failure than a missing marker; say so."""
    monkeypatch.setattr(
        "rclone_bisync_manager.subprocess_executor.check_command_output",
        lambda command: (False, "", "directory not found"),
    )
    reason = check_access_marker("remote:gone", "RCLONE_TEST")
    assert "not reachable" in reason
    assert "directory not found" in reason
