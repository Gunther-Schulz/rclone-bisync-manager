import os
import hashlib

import psutil
from rclone_bisync_manager.env_helpers import env_dir
from rclone_bisync_manager.logging_utils import log_message, log_error
from rclone_bisync_manager.config import get_config
from rclone_bisync_manager.runtime_paths import get_lock_file_path, get_sync_lock_file_path
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


# Option names (normalized to hyphens) that change WHICH FILES rclone sees. Changing any of
# them drops files out of the listings, and bisync reads a file missing from the listing as a
# deletion -- and then deletes it for real on the other side. rclone only guards --filters-file;
# everything else here is invisible to it, so we fingerprint them ourselves.
FILTER_AFFECTING_OPTIONS = (
    'exclude', 'include', 'filter', 'files-from',
    'min-size', 'max-size', 'min-age', 'max-age',
)


def _is_filter_option(key):
    normalized = str(key).replace('_', '-')
    return any(normalized.startswith(name) for name in FILTER_AFFECTING_OPTIONS)


def compute_filter_fingerprint(job, cfg):
    """Hash everything that decides which files this job filters out.

    Covers the filters file AND the exclude/include/filter options, from both global and job
    config. Hashing only the file (as this used to) left every --exclude in rclone_options
    unguarded: add one, and the newly-excluded files get deleted on the other side.
    """
    parts = []

    rules_file = getattr(cfg, 'exclusion_rules_file', None)
    if rules_file and os.path.exists(rules_file):
        parts.append(f"file:{calculate_md5(rules_file)}")

    merged = {}
    for source in (cfg.rclone_options, cfg.bisync_options, cfg.resync_options,
                   job.rclone_options, job.bisync_options, job.resync_options):
        merged.update(source or {})
    for key in sorted(merged):
        if _is_filter_option(key):
            parts.append(f"opt:{str(key).replace('_', '-')}={merged[key]!r}")

    return hashlib.md5("\n".join(parts).encode('utf-8')).hexdigest()


def handle_filter_changes():
    """Force a resync of any job whose filtering changed since its last run.

    The pending resync is recorded in the sync state, which survives a config reload. It used to
    be set on the in-memory job objects, which load_and_validate_config immediately rebuilt from
    YAML -- and because the new hash had ALREADY been written, the resync was then lost forever.

    Per job, not global: a filter change used to resync EVERY job, so one tweak could trigger a
    full resync of an unrelated multi-hundred-gigabyte remote.
    """
    from rclone_bisync_manager.sync_state_store import get_sync_state_store

    cfg = get_config()
    if not cfg._config:
        return
    rules_file = cfg._config.exclusion_rules_file
    if rules_file and not os.path.exists(rules_file):
        log_message(f"Exclusion rules file not found: {rules_file}")

    store = get_sync_state_store()
    changed = []
    for job_key, job in cfg._config.sync_jobs.items():
        fingerprint = compute_filter_fingerprint(job, cfg._config)
        previous = store.sync_state.filter_fingerprints.get(job_key)
        # No previous fingerprint means we have never recorded one (fresh install, or an upgrade
        # from a version without them). Record it, but don't force a resync off the back of it --
        # that would make upgrading kick off a full resync of every job.
        if previous is not None and previous != fingerprint:
            changed.append(job_key)
            store.sync_state.resync_status[job_key] = "NONE"  # back into the resync branch
        store.sync_state.filter_fingerprints[job_key] = fingerprint

    if changed:
        log_message(
            f"Filters changed for {', '.join(changed)}: each will resync before its next sync, "
            f"so newly-excluded files are not mistaken for deletions."
        )
    # Pending resync and new fingerprint are written together, so a crash can't leave the
    # fingerprint updated with the resync forgotten.
    store.save()


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
            if pid == os.getpid():
                # The lock is ours. This function is called twice -- once to serialize `daemon
                # start`, then again by the daemon for its lifecycle lock -- and that only looked
                # like two different processes because of the double fork. When systemd supervises
                # us we don't daemonize, so the second call must not report us as a second daemon.
                # The lock itself is already held (fcntl locks are per-process); just hand back a
                # usable descriptor.
                return os.open(lock_file_path, os.O_RDWR), None
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


def daemon_is_running():
    """Is a live daemon holding the lock file? Read-only: never removes anything.

    The one-off `sync` command used to test os.path.exists() on the lock file, so a lock left
    behind by a SIGKILLed daemon blocked every future manual sync, permanently.
    """
    lock_file_path = get_lock_file_path()
    if not os.path.exists(lock_file_path):
        return False
    try:
        with open(lock_file_path, 'r', encoding='utf-8', errors='replace') as lock_file:
            pid = int(lock_file.read().strip())
    except (ValueError, OSError, UnicodeDecodeError):
        return False  # Unreadable or truncated: treat as stale, not as a running daemon.
    try:
        if not psutil.pid_exists(pid):
            return False
        cmdline = ' '.join(psutil.Process(pid).cmdline() or [])
        return 'rclone-bisync-manager' in cmdline
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def acquire_sync_lock():
    """Acquire the exclusive lock for a one-off sync. Returns (fd, None) or (None, error_str).

    Uses its own lock file, opened without truncation, and lockf -- the same lock family the
    daemon uses. Previously this opened the DAEMON's lock file with 'w' (wiping its PID) and took
    an flock, which on Linux does not interact with the daemon's lockf at all, so the two could
    run concurrently against the same paths.
    """
    lock_file_path = get_sync_lock_file_path()
    try:
        fd = os.open(lock_file_path, os.O_CREAT | os.O_RDWR)
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        return fd, None
    except (IOError, OSError):
        try:
            os.close(fd)
        except (OSError, UnboundLocalError, NameError):
            pass
        return None, "Another sync instance is already running."


def release_sync_lock(lock_fd):
    """Release the one-off sync lock.

    The file is left in place on purpose. Unlinking a lock file while another process holds a
    lock on it is the classic unlink race: the next process creates a fresh inode, locks that,
    and runs concurrently with the holder of the old one.
    """
    if lock_fd is None:
        return
    try:
        fcntl.lockf(lock_fd, fcntl.LOCK_UN)
    except (IOError, OSError):
        pass
    try:
        os.close(lock_fd)
    except (OSError, TypeError):
        pass
