from datetime import datetime
import heapq
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from croniter import croniter
from rclone_bisync_manager.config import config, sync_state


@dataclass(order=True)
class SyncTask:
    scheduled_time: datetime
    path_key: str = field(compare=False)


class SyncScheduler:
    def __init__(self):
        self.tasks: List[SyncTask] = []
        self.task_map: Dict[str, SyncTask] = {}

    def schedule_tasks(self):
        self.check_missed_jobs()
        now = datetime.now()
        for key, job in config._config.sync_jobs.items():
            if job.active:
                cron_obj = croniter(job.schedule, now)
                next_run = cron_obj.get_next(datetime)
                self.schedule_task(key, next_run)

    def check_missed_jobs(self):
        if not config._config.run_missed_jobs:
            return

        now = datetime.now()
        for key, job in config._config.sync_jobs.items():
            if job.active:
                last_sync = sync_state.last_sync_times.get(key)
                if last_sync is None:
                    self.schedule_task(key, now)
                else:
                    cron_obj = croniter(job.schedule, last_sync)
                    next_run = cron_obj.get_next(datetime)
                    while next_run < now:
                        self.schedule_task(key, next_run)
                        next_run = cron_obj.get_next(datetime)

    def schedule_task(self, path_key: str, scheduled_time: datetime):
        if path_key in self.task_map:
            self.remove_task(path_key)
        task = SyncTask(scheduled_time, path_key)
        heapq.heappush(self.tasks, task)
        self.task_map[path_key] = task
        sync_state.update_job_state(path_key, next_run=scheduled_time)
        config.save_sync_state()

    def remove_task(self, path_key: str):
        if path_key in self.task_map:
            task = self.task_map.pop(path_key)
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

    def get_all_tasks(self) -> List[SyncTask]:
        return sorted(self.tasks)


scheduler = SyncScheduler()
