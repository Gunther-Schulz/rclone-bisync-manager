"""Single source of truth for daemon runtime paths (sockets, lock, crash log)."""

import os
from pathlib import Path

# Base directory for runtime files; overridable via env (e.g. tests, XDG_RUNTIME_DIR).
_def = (
    os.environ.get("RCLONE_BISYNC_MANAGER_RUNTIME_DIR")
    or os.environ.get("XDG_RUNTIME_DIR")
    or "/tmp"
)
_runtime_base = Path((_def or "").strip() or "/tmp")


def get_status_socket_path() -> str:
    return str(_runtime_base / "rclone_bisync_manager_status.sock")


def get_add_sync_socket_path() -> str:
    return str(_runtime_base / "rclone_bisync_manager_add_sync.sock")


def get_lock_file_path() -> str:
    return str(_runtime_base / "rclone_bisync_manager.lock")


def get_crash_log_path() -> str:
    return str(_runtime_base / "rclone_bisync_manager_crash.log")


def clear_crash_log() -> bool:
    """Remove the crash log file if it exists. Returns True if removed, False otherwise."""
    path = get_crash_log_path()
    if os.path.exists(path):
        try:
            os.remove(path)
            return True
        except OSError:
            return False
    return False


def write_crash_log(error_message: str) -> None:
    """Write error message to the crash log file (e.g. when daemon crashes)."""
    path = get_crash_log_path()
    crash_dir = os.path.dirname(path)
    if crash_dir:
        os.makedirs(crash_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8", errors="replace") as f:
        f.write(error_message)


def read_crash_log() -> str | None:
    """Read crash log content if present. Returns None if missing or on read error."""
    path = get_crash_log_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None
