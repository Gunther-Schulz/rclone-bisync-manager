from datetime import datetime
import heapq
import threading
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from croniter import croniter
from rclone_bisync_manager.sync_state_store import get_sync_state_store


@dataclass(order=True)
class SyncTask:
    scheduled_time: datetime
    path_key: str = field(compare=False)


class SyncScheduler:
    """Cron scheduler for sync jobs.

    Reload runs on the status-server thread while the main loop reads the heap, so every
    method that touches tasks/task_map holds _lock. It is reentrant because schedule_tasks
    calls check_missed_jobs and schedule_task.
    """

    def __init__(self):
        self.tasks: List[SyncTask] = []
        self.task_map: Dict[str, SyncTask] = {}
        self._lock = threading.RLock()

    def schedule_tasks(self, sync_jobs: Dict[str, Any], run_missed_jobs: bool):
        with self._lock:
            self.check_missed_jobs(sync_jobs, run_missed_jobs)
            now = datetime.now()
            for key, job in sync_jobs.items():
                if not getattr(job, "active", True):
                    continue
                schedule = getattr(job, "schedule", None)
                if not schedule or not str(schedule).strip():
                    continue  # Manual-only job: no schedule
                try:
                    # Don't overwrite a missed run: if we already have a task due (scheduled_time <= now), keep it
                    existing = self.task_map.get(key)
                    if existing is not None and existing.scheduled_time <= now:
                        continue
                    cron_obj = croniter(schedule, now)
                    next_run = cron_obj.get_next(datetime)
                    self.schedule_task(key, next_run)
                except (ValueError, TypeError):
                    pass  # Skip job with invalid schedule

    def check_missed_jobs(self, sync_jobs: Dict[str, Any], run_missed_jobs: bool):
        """Schedule jobs that missed an occurrence while the daemon was down.

        A job that has never synced has not missed anything -- it is new. Scheduling it for
        `now` here is what made adding a job to the config start a full resync the moment
        the config was reloaded. Never-synced jobs fall through to normal cron scheduling;
        use run_initial_sync_on_startup to sync them at startup on purpose.
        """
        if not run_missed_jobs:
            return

        now = datetime.now()
        for key, job in sync_jobs.items():
            if not getattr(job, "active", True):
                continue
            schedule = getattr(job, "schedule", None)
            if not schedule or not str(schedule).strip():
                continue  # Manual-only job: no schedule
            store = get_sync_state_store()
            last_sync = store.sync_state.last_sync_times.get(key)
            if last_sync is None or not isinstance(last_sync, datetime):
                continue  # Never synced: not a missed run.
            try:
                cron_obj = croniter(schedule, last_sync)
                next_run = cron_obj.get_next(datetime)
                while next_run < now:
                    self.schedule_task(key, next_run)
                    next_run = cron_obj.get_next(datetime)
            except (ValueError, TypeError):
                continue  # Invalid schedule: leave it to schedule_tasks to skip

    def schedule_task(self, path_key: str, scheduled_time: datetime):
        with self._lock:
            if path_key in self.task_map:
                self.remove_task(path_key)
            task = SyncTask(scheduled_time, path_key)
            heapq.heappush(self.tasks, task)
            self.task_map[path_key] = task
        store = get_sync_state_store()
        store.sync_state.update_job_state(path_key, next_run=scheduled_time)
        store.save()

    def remove_task(self, path_key: str):
        with self._lock:
            if path_key in self.task_map:
                task = self.task_map.pop(path_key)
                if task in self.tasks:
                    self.tasks.remove(task)
                    heapq.heapify(self.tasks)

    def get_next_task(self) -> Optional[SyncTask]:
        with self._lock:
            return self.tasks[0] if self.tasks else None

    def pop_next_task(self) -> Optional[SyncTask]:
        with self._lock:
            if self.tasks:
                task = heapq.heappop(self.tasks)
                # pop(key, None): a concurrent clear_tasks() may already have emptied the map.
                self.task_map.pop(task.path_key, None)
                return task
            return None

    def clear_tasks(self):
        with self._lock:
            self.tasks.clear()
            self.task_map.clear()


scheduler = SyncScheduler()
