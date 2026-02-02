"""Single source of truth for daemon runtime paths (sockets, lock, crash log)."""

# Socket and lock paths under /tmp; can be overridden via env later if needed.
_STATUS_SOCKET = "/tmp/rclone_bisync_manager_status.sock"
_ADD_SYNC_SOCKET = "/tmp/rclone_bisync_manager_add_sync.sock"
_LOCK_FILE = "/tmp/rclone_bisync_manager.lock"
_CRASH_LOG = "/tmp/rclone_bisync_manager_crash.log"


def get_status_socket_path() -> str:
    return _STATUS_SOCKET


def get_add_sync_socket_path() -> str:
    return _ADD_SYNC_SOCKET


def get_lock_file_path() -> str:
    return _LOCK_FILE


def get_crash_log_path() -> str:
    return _CRASH_LOG
