"""Single source of truth for status JSON keys (server builds with these; tray/CLI consume with these)."""

# Top-level keys (success response)
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
