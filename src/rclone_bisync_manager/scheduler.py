from datetime import datetime
import heapq
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from croniter import croniter
from rclone_bisync_manager.sync_state_store import get_sync_state_store


@dataclass(order=True)
class SyncTask:
    scheduled_time: datetime
    path_key: str = field(compare=False)


class SyncScheduler:
    def __init__(self):
        self.tasks: List[SyncTask] = []
        self.task_map: Dict[str, SyncTask] = {}

    def schedule_tasks(self, sync_jobs: Dict[str, Any], run_missed_jobs: bool):
        self.check_missed_jobs(sync_jobs, run_missed_jobs)
        now = datetime.now()
        for key, job in sync_jobs.items():
            if getattr(job, "active", True):
                try:
                    cron_obj = croniter(job.schedule, now)
                    next_run = cron_obj.get_next(datetime)
                    self.schedule_task(key, next_run)
                except (ValueError, TypeError):
                    pass  # Skip job with invalid schedule

    def check_missed_jobs(self, sync_jobs: Dict[str, Any], run_missed_jobs: bool):
        if not run_missed_jobs:
            return

        now = datetime.now()
        for key, job in sync_jobs.items():
            if getattr(job, "active", True):
                store = get_sync_state_store()
                last_sync = store.sync_state.last_sync_times.get(key)
                if last_sync is None or not isinstance(last_sync, datetime):
                    self.schedule_task(key, now)
                else:
                    try:
                        cron_obj = croniter(job.schedule, last_sync)
                        next_run = cron_obj.get_next(datetime)
                        while next_run < now:
                            self.schedule_task(key, next_run)
                            next_run = cron_obj.get_next(datetime)
                    except (ValueError, TypeError):
                        self.schedule_task(key, now)

    def schedule_task(self, path_key: str, scheduled_time: datetime):
        if path_key in self.task_map:
            self.remove_task(path_key)
        task = SyncTask(scheduled_time, path_key)
        heapq.heappush(self.tasks, task)
        self.task_map[path_key] = task
        store = get_sync_state_store()
        store.sync_state.update_job_state(path_key, next_run=scheduled_time)
        store.save()

    def remove_task(self, path_key: str):
        if path_key in self.task_map:
            task = self.task_map.pop(path_key)
            if task in self.tasks:
                self.tasks.remove(task)
                heapq.heapify(self.tasks)

    def get_next_task(self) -> Optional[SyncTask]:
        return self.tasks[0] if self.tasks else None

    def pop_next_task(self) -> Optional[SyncTask]:
        if self.tasks:
            task = heapq.heappop(self.tasks)
            del self.task_map[task.path_key]
            return task
        return None

    def clear_tasks(self):
        self.tasks.clear()
        self.task_map.clear()


scheduler = SyncScheduler()
