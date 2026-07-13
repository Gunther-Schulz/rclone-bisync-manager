"""The daemon must be able to stop a running rclone.

Nothing held a handle on it before, so `daemon stop` could only wait for the sync to finish on
its own -- hours, for a large resync -- and meanwhile the whole daemon was blocked.
"""

import subprocess
import threading
import time

import pytest

import rclone_bisync_manager.subprocess_executor as se


def test_terminate_returns_false_when_nothing_is_running():
    assert se.terminate_current_child() is False


def test_a_running_child_can_be_terminated():
    """Start a long sleep through the tracked runner and stop it from another thread."""
    result = {}

    def run():
        result["proc"] = se._run_tracked(["sleep", "60"])

    t = threading.Thread(target=run)
    t.start()

    # Wait for it to register as the current child.
    for _ in range(50):
        with se._current_child_lock:
            if se._current_child is not None:
                break
        time.sleep(0.05)

    assert se.terminate_current_child(grace_seconds=5) is True
    t.join(timeout=10)
    assert not t.is_alive(), "the tracked child did not exit after being terminated"
    assert result["proc"].returncode != 0  # killed, not a clean exit


def test_the_whole_process_group_dies_not_just_the_wrapper():
    """cpulimit wraps rclone, so signalling only the direct child would leave rclone running.
    The child gets its own session, so we can signal the entire group."""
    started = threading.Event()

    def run():
        started.set()
        se._run_tracked(["sh", "-c", "sleep 60 & wait"])

    t = threading.Thread(target=run)
    t.start()
    started.wait(timeout=5)

    for _ in range(50):
        with se._current_child_lock:
            proc = se._current_child
        if proc is not None:
            break
        time.sleep(0.05)

    import os
    pgid = os.getpgid(proc.pid)
    assert pgid != os.getpgid(0), "child must be in its OWN process group, or we'd signal ourselves"

    assert se.terminate_current_child(grace_seconds=5) is True
    t.join(timeout=10)
    assert not t.is_alive()


def test_child_is_deregistered_after_a_normal_run():
    """A finished process must not linger as 'current', or shutdown would try to kill a dead pid."""
    se._run_tracked(["true"])
    with se._current_child_lock:
        assert se._current_child is None


def test_tracked_run_returns_exit_code_and_output():
    result = se._run_tracked(["sh", "-c", "echo hello; exit 7"])
    assert result.returncode == 7
    assert "hello" in result.stdout
