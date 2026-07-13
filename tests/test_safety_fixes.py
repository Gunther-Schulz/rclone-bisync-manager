"""Tests for the data-safety fixes: resync recovery, dry-run, option precedence, --force."""

import argparse

import pytest

from rclone_bisync_manager.sync import (
    RESYNC_PENDING_STATES,
    RESYNC_REQUIRED_EXIT_CODES,
    get_rclone_args,
)


class FakeJob:
    def __init__(self, rclone_options=None, bisync_options=None, resync_options=None):
        self.rclone_options = rclone_options or {}
        self.bisync_options = bisync_options or {}
        self.resync_options = resync_options or {}


class FakeContext:
    def __init__(self, job=None, rclone_options=None, bisync_options=None,
                 resync_options=None, dry_run=False, force_bisync=False):
        self.job_key = "j1"
        self.job = job or FakeJob()
        self.rclone_options = rclone_options or {}
        self.bisync_options = bisync_options or {}
        self.resync_options = resync_options or {}
        self.dry_run = dry_run
        self.force_bisync = force_bisync
        self.exclusion_rules_file = None
        self.redirect_rclone_log_output = False
        self.log_file_path = None


def arg_value(args, flag):
    """Return the value following `flag`, or None if the flag is absent."""
    return args[args.index(flag) + 1] if flag in args else None


# --- A killed resync must not strand the job ------------------------------------------

def test_failed_resync_is_retried():
    """A resync killed by SIGTERM records FAILED. If FAILED isn't a pending state, the job
    skips the resync branch forever and runs a bisync that can never find a baseline."""
    assert "FAILED" in RESYNC_PENDING_STATES
    assert "NONE" in RESYNC_PENDING_STATES
    assert "IN_PROGRESS" in RESYNC_PENDING_STATES


def test_completed_resync_is_not_redone():
    """A healthy job must not resync on every run."""
    assert "COMPLETED" not in RESYNC_PENDING_STATES


def test_exit_7_is_treated_as_needing_resync():
    """rclone exits 7 on 'Bisync aborted. Must run --resync to recover'."""
    assert 7 in RESYNC_REQUIRED_EXIT_CODES
    assert 0 not in RESYNC_REQUIRED_EXIT_CODES
    assert 9 not in RESYNC_REQUIRED_EXIT_CODES  # 9 = nothing transferred = success


# --- Option precedence ----------------------------------------------------------------

def test_job_option_beats_global_option():
    """A job asking to be STRICTER than the global must win. The global op-options dict was
    spread last, so the global silently overrode the job."""
    ctx = FakeContext(
        rclone_options={"max_delete": 50},
        bisync_options={"max_delete": 90},
        job=FakeJob(rclone_options={"max_delete": 1}),
    )
    assert arg_value(get_rclone_args("bisync", ctx), "--max-delete") == "1"


def test_job_bisync_options_are_read():
    """job.bisync_options was never read by anything, though the config editor writes it."""
    ctx = FakeContext(job=FakeJob(bisync_options={"conflict_resolve": "newer"}))
    assert arg_value(get_rclone_args("bisync", ctx), "--conflict-resolve") == "newer"


def test_job_bisync_options_beat_job_rclone_options():
    ctx = FakeContext(job=FakeJob(rclone_options={"max_delete": 5},
                                  bisync_options={"max_delete": 7}))
    assert arg_value(get_rclone_args("bisync", ctx), "--max-delete") == "7"


def test_resync_uses_resync_options_not_bisync_options():
    ctx = FakeContext(bisync_options={"max_delete": 90}, resync_options={"max_delete": 3})
    assert arg_value(get_rclone_args("resync", ctx), "--max-delete") == "3"


# --- --force must not silently disable the delete guard --------------------------------

def test_force_is_absent_by_default():
    assert "--force" not in get_rclone_args("bisync", FakeContext())


def test_force_is_passed_on_bisync_when_requested():
    """--force bypasses --max-delete; it must appear only when actually asked for."""
    assert "--force" in get_rclone_args("bisync", FakeContext(force_bisync=True))


def test_force_is_never_passed_on_resync():
    """Resync doesn't delete, so --force means nothing there -- and its only effect is to
    disable the deletion guard."""
    assert "--force" not in get_rclone_args("resync", FakeContext(force_bisync=True))


# --- dry-run --------------------------------------------------------------------------

def test_dry_run_flag_is_emitted():
    assert "--dry-run" in get_rclone_args("bisync", FakeContext(dry_run=True))


def test_no_dry_run_flag_when_off():
    assert "--dry-run" not in get_rclone_args("bisync", FakeContext(dry_run=False))
