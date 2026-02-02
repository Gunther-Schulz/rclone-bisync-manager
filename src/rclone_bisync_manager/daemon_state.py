"""Daemon runtime state (lifecycle, queue, lock). Separate from config (loaded YAML, persistence)."""

from queue import Queue
from threading import Lock

# Set by daemon_main() when daemon starts; None when not running as daemon.
daemon_state = None


class DaemonRuntimeState:
    """Holds daemon-only runtime: loop flags, sync queue, lock fd. Not config or persistence."""

    def __init__(self):
        self.running = True
        self.shutting_down = False
        self.shutdown_complete = False
        self.sync_queue = Queue()
        self.queued_paths = set()
        self.sync_lock = Lock()
        self.currently_syncing = None
        self.current_sync_start_time = None
        self.args = None
        self.lock_fd = None
