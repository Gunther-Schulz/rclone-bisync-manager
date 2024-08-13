from datetime import datetime
import heapq
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from config import config


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
        for key, cron in config.sync_schedules.items():
            next_run = cron.get_next(now)
            self.schedule_task(key, next_run)

    def check_missed_jobs(self):
        if not config.run_missed_jobs:
            return

        now = datetime.now()
        for key, cron in config.sync_schedules.items():
            last_sync = config.last_sync_times.get(key)
            if last_sync is None:
                # If there's no last sync time, schedule it immediately
                self.schedule_task(key, now)
            else:
                next_run = cron.get_next(last_sync)
                while next_run < now:
                    self.schedule_task(key, next_run)
                    next_run = cron.get_next(next_run)

    def schedule_task(self, path_key: str, scheduled_time: datetime):
        if path_key in self.task_map:
            self.remove_task(path_key)
        task = SyncTask(scheduled_time, path_key)
        heapq.heappush(self.tasks, task)
        self.task_map[path_key] = task

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
