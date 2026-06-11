"""Regression: a missing cpulimit must NOT abort the sync.

execute_rclone_command previously called run_with_cpulimit unconditionally when
a CPU limit was configured, and run_with_cpulimit raises if cpulimit is absent --
aborting the whole sync before rclone ran. It must instead degrade gracefully and
run rclone without CPU limiting.
"""

import pytest

from rclone_bisync_manager import subprocess_executor as se


def test_missing_cpulimit_falls_back_to_run_command(monkeypatch):
    """cpulimit absent -> run rclone directly, no exception."""
    calls = {}
    # rclone present, cpulimit absent
    monkeypatch.setattr(se, "check_command_exists", lambda cmd: cmd != "cpulimit")

    def _no_cpulimit(*a, **k):
        raise AssertionError("run_with_cpulimit must not be called when cpulimit is absent")

    def _run(args, timeout=None):
        calls["ran"] = args
        return "OK"

    monkeypatch.setattr(se, "run_with_cpulimit", _no_cpulimit)
    monkeypatch.setattr(se, "run_command", _run)

    result = se.execute_rclone_command(["rclone", "bisync"], cpulimit_percent=50)

    assert result == "OK"
    assert calls["ran"] == ["rclone", "bisync"]


def test_present_cpulimit_uses_run_with_cpulimit(monkeypatch):
    """cpulimit present -> use it (no behavior change)."""
    calls = {}
    monkeypatch.setattr(se, "check_command_exists", lambda cmd: True)

    def _limited(args, pct, timeout=None):
        calls["limited"] = (args, pct)
        return "LIMITED"

    def _no_direct(*a, **k):
        raise AssertionError("run_command must not be called when cpulimit is available")

    monkeypatch.setattr(se, "run_with_cpulimit", _limited)
    monkeypatch.setattr(se, "run_command", _no_direct)

    result = se.execute_rclone_command(["rclone", "bisync"], cpulimit_percent=50)

    assert result == "LIMITED"
    assert calls["limited"] == (["rclone", "bisync"], 50)


def test_invalid_cpulimit_percent_still_raises(monkeypatch):
    """A nonsensical percentage is still a hard error (unchanged)."""
    monkeypatch.setattr(se, "check_command_exists", lambda cmd: True)
    with pytest.raises(se.SubprocessError):
        se.execute_rclone_command(["rclone", "bisync"], cpulimit_percent=150)
