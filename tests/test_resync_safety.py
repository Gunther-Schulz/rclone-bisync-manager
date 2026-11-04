"""A resync must neither run without rclone asking for one nor overwrite unsynced local work.

The defect these pin: rclone aborted a bisync with exit 7 on a transient HiDrive listing error and
said "Error is retryable without --resync due to --resilient mode". The manager resynced anyway,
and the plain `--resync` (= --resync-mode path1, the remote) replaced local edits that had not
been uploaded yet with the remote's older versions -- silently.
"""

import os
from types import SimpleNamespace

import pytest

from rclone_bisync_manager import sync
from rclone_bisync_manager.sync import (
    RESYNC_BACKUP_DIRNAME,
    resync_verdict,
    resync_safety_args,
    perform_sync_operations,
)

RETRYABLE_OUTPUT = (
    "ERROR : There were errors while building listings. Aborting as it is too dangerous to continue.\n"
    "ERROR : Bisync aborted. Error is retryable without --resync due to --resilient mode.\n"
)
REQUIRED_OUTPUT = "ERROR : Bisync aborted. Must run --resync to recover.\n"


# --- rclone's verdict, read from its own output ------------------------------------------

def test_verdict_retryable():
    assert resync_verdict(RETRYABLE_OUTPUT) == "retryable"


def test_verdict_required():
    assert resync_verdict(REQUIRED_OUTPUT) == "required"


def test_verdict_unknown_when_rclone_said_neither():
    assert resync_verdict("ERROR : something else entirely\n") == "unknown"
    assert resync_verdict("") == "unknown"


# --- the decision after an exit-7 abort -----------------------------------------------------

class FakeSyncState:
    def __init__(self):
        self.sync_status = {"j1": "COMPLETED"}
        self.resync_status = {"j1": "COMPLETED"}
        self.last_sync_times = {}

    def update_job_state(self, key, sync_status=None, resync_status=None, last_sync=None):
        if sync_status is not None:
            self.sync_status[key] = sync_status
        if resync_status is not None:
            self.resync_status[key] = resync_status


class FakeStore:
    def __init__(self):
        self.sync_state = FakeSyncState()
        self.sync_errors = {}

    def save(self):
        pass

    def update_sync_error(self, local_path, sync_type, code, message):
        self.sync_errors[local_path] = {"sync_type": sync_type, "error_code": code, "message": message}

    def remove_sync_error(self, local_path):
        self.sync_errors.pop(local_path, None)


def make_context(tmp_path, store):
    job = SimpleNamespace(local="job1", rclone_remote="r", remote="job1",
                          rclone_options={}, bisync_options={}, resync_options={})
    return SimpleNamespace(
        job_key="j1", job=job, local_base_path=str(tmp_path), dry_run=False,
        force_bisync=False, force_resync=False, state_store=store,
        rclone_options={}, bisync_options={}, resync_options={},
        log_state=SimpleNamespace(last_log_position=0, hash_warnings={}),
    )


@pytest.fixture
def run_after_exit_7(tmp_path, monkeypatch):
    """Run one sync whose bisync aborts with exit 7 and the given rclone output."""
    def run(output):
        store = FakeStore()
        calls = {"resync": 0, "notify": []}
        monkeypatch.setattr(sync, "bisync", lambda *a, **k: ("FAILED", 7, output))
        monkeypatch.setattr(sync, "resync", lambda *a, **k: calls.__setitem__("resync", calls["resync"] + 1))
        monkeypatch.setattr(sync, "notify_user", lambda title, body: calls["notify"].append(title))
        perform_sync_operations("j1", context=make_context(tmp_path, store))
        return store, calls
    return run


def test_retryable_abort_does_not_schedule_a_resync(run_after_exit_7):
    store, calls = run_after_exit_7(RETRYABLE_OUTPUT)
    assert store.sync_state.resync_status["j1"] == "COMPLETED"
    assert calls["resync"] == 0


def test_required_abort_schedules_a_resync(run_after_exit_7):
    store, _ = run_after_exit_7(REQUIRED_OUTPUT)
    assert store.sync_state.resync_status["j1"] == "FAILED"


def test_abort_without_verdict_does_not_resync_and_tells_the_user(run_after_exit_7):
    """Neither marker: we cannot know the listings are unusable, so no automatic resync --
    but the user must hear about it, not find it in a log."""
    store, calls = run_after_exit_7("ERROR : unexpected\n")
    assert store.sync_state.resync_status["j1"] == "COMPLETED"
    assert calls["resync"] == 0
    assert calls["notify"], "an exit 7 without rclone's verdict must notify the user"


# --- a resync that does run keeps the newer file and backs up the loser ---------------------

def test_resync_defaults_to_newer_wins(tmp_path):
    ctx = make_context(tmp_path, FakeStore())
    args = resync_safety_args("j1", os.path.join(str(tmp_path), "job1"), ctx, stamp="20261103_083001")
    assert args[args.index("--resync-mode") + 1] == "newer"


def test_resync_backs_up_replaced_local_files_outside_the_job(tmp_path):
    local = os.path.join(str(tmp_path), "job1")
    ctx = make_context(tmp_path, FakeStore())
    args = resync_safety_args("j1", local, ctx, stamp="20261103_083001")
    backup = args[args.index("--backup-dir2") + 1]
    assert backup == os.path.join(str(tmp_path), RESYNC_BACKUP_DIRNAME, "j1", "20261103_083001")
    # rclone refuses an overlapping backup dir, and one inside the job would sync up as data.
    assert os.path.commonpath([backup, local]) != local


def test_configured_resync_mode_and_backup_dir_are_respected(tmp_path):
    ctx = make_context(tmp_path, FakeStore())
    ctx.job.resync_options = {"resync_mode": "path1", "backup_dir2": "/elsewhere"}
    args = resync_safety_args("j1", os.path.join(str(tmp_path), "job1"), ctx, stamp="x")
    assert "--resync-mode" not in args
    assert "--backup-dir2" not in args


def test_no_backup_dir_when_the_job_is_the_base_path(tmp_path):
    """A job whose local path IS the base would contain the backup dir; skip it rather than
    hand rclone an overlapping path (it would abort the resync)."""
    ctx = make_context(tmp_path, FakeStore())
    args = resync_safety_args("j1", str(tmp_path), ctx, stamp="x")
    assert "--backup-dir2" not in args
    assert args[args.index("--resync-mode") + 1] == "newer"


# --- review round on 8b02c0c ------------------------------------------------------------------

MISSING_LISTINGS_RESILIENT = (
    "ERROR : Bisync critical error: cannot find prior Path1 or Path2 listings, likely due to "
    "critical error on prior run\n"
    "ERROR : Bisync aborted. Error is retryable without --resync due to --resilient mode.\n"
)


def test_missing_listings_need_a_resync_even_under_resilient():
    """rclone 1.75.1 calls missing listings 'retryable' under --resilient, but a bisync cannot
    create listings: the retry can never succeed, and the job would loop forever."""
    assert resync_verdict(MISSING_LISTINGS_RESILIENT) == "required"


def test_missing_listings_schedule_a_resync(run_after_exit_7):
    store, _ = run_after_exit_7(MISSING_LISTINGS_RESILIENT)
    assert store.sync_state.resync_status["j1"] == "FAILED"


def test_repeated_retryable_aborts_reach_the_user(tmp_path, monkeypatch):
    """A retryable abort heals itself and stays quiet; one that keeps recurring does not heal,
    and must not stay quiet."""
    sync.RETRYABLE_STREAK.clear()
    notes = []
    monkeypatch.setattr(sync, "bisync", lambda *a, **k: ("FAILED", 7, RETRYABLE_OUTPUT))
    monkeypatch.setattr(sync, "notify_user", lambda title, body: notes.append(title))
    store = FakeStore()
    for _ in range(sync.RETRYABLE_NOTIFY_AFTER - 1):
        perform_sync_operations("j1", context=make_context(tmp_path, store))
    assert notes == []
    perform_sync_operations("j1", context=make_context(tmp_path, store))
    assert len(notes) == 1


def test_a_successful_bisync_resets_the_retryable_streak(tmp_path, monkeypatch):
    sync.RETRYABLE_STREAK.clear()
    sync.RETRYABLE_STREAK["j1"] = sync.RETRYABLE_NOTIFY_AFTER - 1
    monkeypatch.setattr(sync, "bisync", lambda *a, **k: ("COMPLETED", 0, ""))
    perform_sync_operations("j1", context=make_context(tmp_path, FakeStore()))
    assert sync.RETRYABLE_STREAK.get("j1", 0) == 0


def test_hyphenated_option_keys_count_as_configured(tmp_path):
    ctx = make_context(tmp_path, FakeStore())
    ctx.job.resync_options = {"resync-mode": "path1", "backup-dir2": "/elsewhere"}
    args = resync_safety_args("j1", os.path.join(str(tmp_path), "job1"), ctx, stamp="x")
    assert "--resync-mode" not in args
    assert "--backup-dir2" not in args


def test_no_backup_dir_inside_another_jobs_tree(tmp_path):
    """A job at the base path (`local: "."`) would sync every other job's backups up as data."""
    ctx = make_context(tmp_path, FakeStore())
    args = resync_safety_args("j1", os.path.join(str(tmp_path), "job1"), ctx, stamp="x",
                              job_paths=[os.path.join(str(tmp_path), "job1"), str(tmp_path)])
    assert "--backup-dir2" not in args


def test_configured_backup_dir_is_reported_not_denied(tmp_path, monkeypatch):
    notes = []
    monkeypatch.setattr(sync, "notify_user", lambda title, body: notes.append(body))
    monkeypatch.setattr(sync, "run_rclone_command", lambda args, ctx: SimpleNamespace(returncode=0, stderr=""))
    ctx = make_context(tmp_path, FakeStore())
    ctx.job.resync_options = {"backup_dir2": "/elsewhere"}
    for attr in ("exclusion_rules_file", "rclone_log_file_path"):
        setattr(ctx, attr, None)
    ctx.redirect_rclone_log_output = False
    sync.resync("j1", "r:job1", os.path.join(str(tmp_path), "job1"), ctx)
    assert notes and "/elsewhere" in notes[0]
    assert "not backed up" not in notes[0]


def test_failed_notification_is_logged(monkeypatch):
    errors = []
    monkeypatch.setattr(sync, "log_error", lambda msg: errors.append(msg))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: SimpleNamespace(returncode=1))
    sync.notify_user("t", "b")
    assert any("exit 1" in e for e in errors)
