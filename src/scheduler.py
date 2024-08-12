from datetime import datetime
import heapq


class SyncTask:
    def __init__(self, path_key, scheduled_time):
        self.path_key = path_key
        self.scheduled_time = scheduled_time

    def __lt__(self, other):
        return self.scheduled_time < other.scheduled_time


class Scheduler:
    def __init__(self):
        self.tasks = []

    def schedule_task(self, path_key, scheduled_time):
        heapq.heappush(self.tasks, SyncTask(path_key, scheduled_time))

    def get_next_task(self):
        if self.tasks:
            return self.tasks[0]
        return None

    def pop_next_task(self):
        if self.tasks:
            return heapq.heappop(self.tasks)
        return None


scheduler = Scheduler()
