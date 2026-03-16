import os
import hashlib

import psutil
from rclone_bisync_manager.env_helpers import env_dir
from rclone_bisync_manager.logging_utils import log_message, log_error
from rclone_bisync_manager.config import get_config
from rclone_bisync_manager.runtime_paths import get_lock_file_path
from rclone_bisync_manager.subprocess_executor import (
    verify_required_tools,
)
import fcntl
import errno


def ensure_local_directory(local_path):
    if not os.path.exists(local_path):
        os.makedirs(local_path, exist_ok=True)
        log_message(f"Created local directory: {local_path}")


def ensure_rclone_dir():
    home = os.path.expanduser(env_dir("HOME", "~"))
    rclone_dir = os.path.join(home, ".cache", "rclone", "bisync")
    if not os.access(rclone_dir, os.W_OK):
        os.makedirs(rclone_dir, exist_ok=True)
        os.chmod(rclone_dir, 0o777)


def handle_filter_changes():
    cfg = get_config()
    if not cfg._config or not cfg._config.exclusion_rules_file:
        return
    stored_md5_file = os.path.join(cfg.cache_dir, '.filter_md5')
    os.makedirs(cfg.cache_dir, exist_ok=True)
    if os.path.exists(cfg._config.exclusion_rules_file):
        current_md5 = calculate_md5(cfg._config.exclusion_rules_file)
        if os.path.exists(stored_md5_file):
            try:
                with open(stored_md5_file, 'r', encoding='utf-8', errors='replace') as f:
                    stored_md5 = f.read().strip()
            except OSError:
                stored_md5 = ""
        else:
            stored_md5 = ""
        if current_md5 != stored_md5:
            with open(stored_md5_file, 'w', encoding='utf-8') as f:
                f.write(current_md5)
            log_message("Filter file has changed. A resync is required.")
            for job_key in cfg._config.sync_jobs:
                cfg._config.sync_jobs[job_key].force_resync = True
    else:
        log_message(f"Exclusion rules file not found: {cfg._config.exclusion_rules_file}")


def calculate_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def check_and_create_lock_file():
    """Check if daemon is already running and create lock file if not.
    Returns (lock_fd, error_message) where lock_fd is None if already running.
    Implements health checks and strong file locking for safety."""
    lock_file_path = get_lock_file_path()

    if os.path.exists(lock_file_path):
        try:
            with open(lock_file_path, 'r', encoding='utf-8', errors='replace') as lock_file:
                pid = int(lock_file.read().strip())
            if psutil.pid_exists(pid):
                process = psutil.Process(pid)
                cmdline = ' '.join(process.cmdline()) if process.cmdline() else ''
                if 'rclone-bisync-manager' in cmdline:
                    # Daemon is running and healthy
                    return None, f"Daemon is already running (PID: {pid})"
                else:
                    # PID exists but doesn't match our process - stale lock
                    log_message(f"Removing stale lock file (PID {pid} no longer running)")
            # If we reach here, the PID doesn't exist or isn't our process - stale lock
            os.remove(lock_file_path)
        except (ValueError, OSError, UnicodeDecodeError, psutil.NoSuchProcess, psutil.AccessDenied) as e:
            log_message(f"Error reading lock file: {str(e)} - removing stale lock")
            try:
                os.remove(lock_file_path)
            except OSError:
                pass

    try:
        # Create lock file with O_EXCL to prevent race conditions
        lock_fd = os.open(lock_file_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        # Acquire exclusive non-blocking lock
        fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Write PID atomically
        os.write(lock_fd, str(os.getpid()).encode())
        os.fsync(lock_fd)  # Force write to disk
        return lock_fd, None
    except IOError as e:
        if e.errno == errno.EEXIST:
            return None, "Unable to create lock file. Another instance might be starting."
        return None, f"Unexpected error creating lock file: {str(e)}"


def acquire_sync_lock():
    """Acquire exclusive lock for one-off sync (non-daemon). Returns (fd, None) or (None, error_str).
    Uses flock for better compatibility across platforms."""
    lock_file_path = get_lock_file_path()
    try:
        fd = open(lock_file_path, 'w')
        # Use flock with non-blocking lock
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd, None
    except (IOError, OSError) as e:
        return None, "Another sync instance is already running."


def release_sync_lock(lock_fd):
    """Release lock and remove lock file after one-off sync."""
    if lock_fd is None:
        return
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
    except (IOError, OSError):
        pass
    try:
        os.unlink(get_lock_file_path())
    except OSError:
        pass
