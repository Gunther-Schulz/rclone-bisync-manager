"""Single source of truth for status JSON keys (server builds with these; tray/CLI consume with these)."""

import enum

# Top-level keys (success response)
VERSION = "version"
PID = "pid"
RUNNING = "running"
SHUTTING_DOWN = "shutting_down"
IN_LIMBO = "in_limbo"
CONFIG_INVALID = "config_invalid"
CONFIG_ERROR_MESSAGE = "config_error_message"
CURRENTLY_SYNCING = "currently_syncing"
QUEUED_PATHS = "queued_paths"
CONFIG_CHANGED_ON_DISK = "config_changed_on_disk"
CONFIG_FILE_LOCATION = "config_file_location"
LOG_FILE_LOCATION = "log_file_location"
SYNC_ERRORS = "sync_errors"
CURRENT_CONFIG = "current_config"
SYNC_JOBS = "sync_jobs"

# Per-job keys (inside sync_jobs[job_key])
LAST_SYNC = "last_sync"
NEXT_RUN = "next_run"
SYNC_STATUS = "sync_status"
RESYNC_STATUS = "resync_status"
HASH_WARNINGS = "hash_warnings"

# Error response keys
STATUS = "status"
MESSAGE = "message"
ERROR = "error"


class DaemonState(enum.Enum):
    """Display state derived from status dict; shared by tray and any CLI/UI consumer."""
    INITIAL = "initial"
    STARTING = "starting"
    RUNNING = "running"
    SYNCING = "syncing"
    SHUTTING_DOWN = "shutting_down"
    SYNC_ISSUES = "sync_issues"
    CONFIG_INVALID = "config_invalid"
    CONFIG_CHANGED = "config_changed"
    LIMBO = "limbo"
    OFFLINE = "offline"
    FAILED = "failed"


def _has_sync_issues(status: dict | None) -> bool:
    if not isinstance(status, dict):
        return False
    sync_jobs = status.get(SYNC_JOBS)
    if not isinstance(sync_jobs, dict):
        sync_jobs = {}
    return (
        any(
            job.get(SYNC_STATUS, "NONE") not in ["COMPLETED", "NONE", "IN_PROGRESS"]
            or job.get(RESYNC_STATUS, "NONE") not in ["COMPLETED", "NONE", "IN_PROGRESS"]
            or job.get(HASH_WARNINGS, False)
            for job in sync_jobs.values()
        )
        or bool(status.get(SYNC_ERRORS))
    )


def status_to_display_state(status: dict | None, daemon_start_error: str | None = None) -> DaemonState:
    """Map status dict (or None) to DaemonState. Pure function; caller sets daemon_start_error when FAILED."""
    if daemon_start_error:
        return DaemonState.FAILED
    if status is None:
        return DaemonState.OFFLINE
    if not isinstance(status, dict):
        return DaemonState.FAILED
    if status.get(STATUS) == "error":
        return DaemonState.FAILED
    if status.get(ERROR):
        return DaemonState.FAILED
    if status.get(SHUTTING_DOWN):
        return DaemonState.SHUTTING_DOWN
    # "Sync in progress" overrides attention states so user sees blue during retries/scheduled syncs
    if status.get(CURRENTLY_SYNCING):
        return DaemonState.SYNCING
    if status.get(IN_LIMBO):
        return DaemonState.LIMBO
    if status.get(CONFIG_INVALID):
        return DaemonState.CONFIG_INVALID
    if _has_sync_issues(status):
        return DaemonState.SYNC_ISSUES
    if status.get(CONFIG_CHANGED_ON_DISK):
        return DaemonState.CONFIG_CHANGED
    if status.get(RUNNING, False):
        return DaemonState.RUNNING
    return DaemonState.OFFLINE
