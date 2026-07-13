"""Tests for scheduler: run_missed_jobs, schedule_tasks, missed run not overwritten."""

from datetime import datetime, timedelta

import pytest

from rclone_bisync_manager.config import SyncJobConfig
from rclone_bisync_manager.scheduler import SyncScheduler
from rclone_bisync_manager.sync_state_store import SyncStateStore


def _job(schedule: str = "0 0 * * *", active: bool = True) -> SyncJobConfig:
    return SyncJobConfig(
        local="subdir",
        rclone_remote="remote",
        remote="path/on/remote",
        schedule=schedule,
        active=active,
    )


def test_schedule_tasks_run_missed_jobs_false_no_missed_scheduled(tmp_path, monkeypatch):
    """With run_missed_jobs=False, no 'missed' run is scheduled for now."""
    store = SyncStateStore(str(tmp_path))
    store.load()
    store.sync_state.last_sync_times["j1"] = datetime.now() - timedelta(days=1)
    store.save()

    sched = SyncScheduler()
    sync_jobs = {"j1": _job()}
    monkeypatch.setattr("rclone_bisync_manager.scheduler.get_sync_state_store", lambda: store)
    sched.schedule_tasks(sync_jobs, run_missed_jobs=False)

    next_task = sched.get_next_task()
    assert next_task is not None
    # Next run should be in the future (next midnight), not "now" or in the past
    assert next_task.scheduled_time > datetime.now()


def test_never_synced_job_is_not_treated_as_a_missed_run(tmp_path, monkeypatch):
    """A job that has never synced has missed nothing: schedule it at its next cron time, not now.

    Scheduling it for "now" meant adding a job to the config and reloading immediately started a
    full resync of it -- on a large remote, an unannounced multi-hour transfer.
    """
    store = SyncStateStore(str(tmp_path))
    store.load()

    sched = SyncScheduler()
    sync_jobs = {"j1": _job()}
    now_before = datetime.now()
    monkeypatch.setattr("rclone_bisync_manager.scheduler.get_sync_state_store", lambda: store)
    sched.schedule_tasks(sync_jobs, run_missed_jobs=True)

    next_task = sched.get_next_task()
    assert next_task is not None
    assert next_task.path_key == "j1"
    # Due in the future (next cron occurrence), NOT immediately.
    assert next_task.scheduled_time > now_before + timedelta(seconds=2)


def test_schedule_tasks_missed_run_not_overwritten(tmp_path, monkeypatch):
    """With run_missed_jobs=True and last_sync in past, missed run is scheduled and not overwritten by next cron."""
    store = SyncStateStore(str(tmp_path))
    store.load()
    # Last sync yesterday 18:00; schedule midnight -> one missed run (midnight today)
    yesterday_18 = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0) - timedelta(days=1)
    store.sync_state.last_sync_times["j1"] = yesterday_18
    store.save()

    sched = SyncScheduler()
    sync_jobs = {"j1": _job(schedule="0 0 * * *")}  # midnight
    monkeypatch.setattr("rclone_bisync_manager.scheduler.get_sync_state_store", lambda: store)
    sched.schedule_tasks(sync_jobs, run_missed_jobs=True)

    next_task = sched.get_next_task()
    assert next_task is not None
    assert next_task.path_key == "j1"
    # Missed run (midnight today) should be in the past or now; must not be tomorrow midnight
    assert next_task.scheduled_time <= datetime.now() + timedelta(seconds=5)
