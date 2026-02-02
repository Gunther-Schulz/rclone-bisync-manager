"""Sync run context: job + global options + log state. Callers build from config and pass into perform_sync_operations."""

from dataclasses import dataclass
from typing import Any, Dict

from rclone_bisync_manager.config import SyncJobConfig


@dataclass
class LogState:
    """Mutable log state updated during sync (last_log_position, hash_warnings)."""
    last_log_position: int
    hash_warnings: Dict[str, Any]


@dataclass
class SyncContext:
    """Everything sync needs for one run: one job + global options + log state."""
    job_key: str
    job: SyncJobConfig
    local_base_path: Any  # DirectoryPath from config
    dry_run: bool
    bisync_options: Dict[str, Any]
    resync_options: Dict[str, Any]
    rclone_options: Dict[str, Any]
    exclusion_rules_file: Any
    redirect_rclone_log_output: bool
    log_file_path: str
    max_cpu_usage_percent: int
    log_state: LogState


def build_sync_context(key: str, config_obj) -> SyncContext:
    """Build SyncContext from config object. Caller should set config_obj._last_log_position = context.log_state.last_log_position after run."""
    c = getattr(config_obj, "_config", None)
    if not c or key not in c.sync_jobs:
        raise ValueError(f"Config not loaded or job '{key}' not in sync_jobs.")
    job = c.sync_jobs[key]
    return SyncContext(
        job_key=key,
        job=job,
        local_base_path=c.local_base_path,
        dry_run=c.dry_run,
        bisync_options=c.bisync_options,
        resync_options=c.resync_options,
        rclone_options=c.rclone_options,
        exclusion_rules_file=getattr(c, "exclusion_rules_file", None),
        redirect_rclone_log_output=getattr(c, "redirect_rclone_log_output", False),
        log_file_path=c.log_file_path,
        max_cpu_usage_percent=getattr(c, "max_cpu_usage_percent", 100),
        log_state=LogState(
            last_log_position=getattr(config_obj, "_last_log_position", 0),
            hash_warnings=getattr(config_obj, "hash_warnings", {}),
        ),
    )
