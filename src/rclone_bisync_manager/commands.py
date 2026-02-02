"""Command layer: one entry point per CLI command. Main dispatches here."""

import json
import os
import signal
import sys
import traceback

import daemon

from rclone_bisync_manager.config import config, signal_handler
from rclone_bisync_manager.daemon_client import request_add_sync, request_reload
from rclone_bisync_manager.daemon_functions import daemon_main, print_daemon_status, stop_daemon
from rclone_bisync_manager.logging_utils import (
    ensure_log_file_path,
    log_config_file_location,
    log_error,
    log_message,
    set_config,
    setup_loggers,
)
from rclone_bisync_manager.runtime_paths import get_lock_file_path
from rclone_bisync_manager.sync import perform_sync_operations
from rclone_bisync_manager.utils import (
    check_and_create_lock_file,
    check_tools,
    ensure_rclone_dir,
    handle_filter_changes,
    acquire_sync_lock,
    release_sync_lock,
)


def run_command(args, config_obj):
    """Dispatch by (command, action). Returns exit code 0 or 1, or never returns (daemon start)."""
    if args.command == "daemon":
        if args.action == "start":
            run_daemon_start(args, config_obj)
            return None  # unreachable
        if args.action == "stop":
            return run_daemon_stop()
        if args.action == "status":
            return run_daemon_status()
        if args.action == "reload":
            return run_daemon_reload(args)
    if args.command == "sync":
        return run_sync(args, config_obj)
    if args.command == "add-sync":
        return run_add_sync(args)
    return 1


def _bootstrap_for_daemon(args, config_obj):
    """Setup logging, tools, dirs, filters before daemonize. Raises on failure."""
    config_obj.initialize_config(args)
    set_config(config_obj)
    ensure_log_file_path()
    setup_loggers(args.console_log)
    log_config_file_location(config_obj.config_file)
    log_message("Daemon initialization started")
    if hasattr(config_obj, "_config") and config_obj._config is not None and hasattr(config_obj._config, "log_file_path"):
        print(f"Using log file: {config_obj._config.log_file_path}")
    else:
        print("Warning: Log file path not set or configuration not loaded properly.")
    print("Checking tools and directories...")
    check_tools()
    ensure_rclone_dir()
    handle_filter_changes()
    if not os.environ.get("HOME"):
        raise ValueError("Unable to determine home directory")


def run_daemon_start(args, config_obj):
    """Bootstrap, lock, then run under DaemonContext. Never returns on success; sys.exit(1) on failure."""
    try:
        print("Initializing daemon...")
        _bootstrap_for_daemon(args, config_obj)
        print("Creating lock file...")
        lock_fd, error_message = check_and_create_lock_file()
        if error_message:
            raise ValueError(f"Error: {error_message}")
        print("Starting daemon process...")
        log_message("Starting daemon in limbo state...")
        with daemon.DaemonContext(
            working_directory="/",
            umask=0o002,
            signal_map={
                signal.SIGTERM: signal_handler,
                signal.SIGINT: signal_handler,
            },
            stdout=sys.stdout,
            stderr=sys.stderr,
        ):
            config_obj.args = args
            print("Daemon process started. Calling daemon_main()...")
            daemon_main()
    except Exception as e:
        error_trace = traceback.format_exc()
        log_error(f"Error starting daemon: {str(e)}\n{error_trace}")
        print(f"Error starting daemon: {str(e)}\nFull traceback:\n{error_trace}")
        sys.exit(1)


def run_daemon_stop():
    """Stop daemon via socket. Returns 0."""
    stop_daemon()
    return 0


def run_daemon_status():
    """Print daemon status. Returns 0."""
    print_daemon_status()
    return 0


def run_daemon_reload(args):
    """Reload daemon config via socket. Returns 0 on success, 1 otherwise."""
    result = request_reload()
    if result is None:
        print("Daemon is not running.")
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "success" else 1


def run_sync(args, config_obj):
    """Run sync jobs (one-off, non-daemon). Returns 0 on success, 1 on error."""
    if os.path.exists(get_lock_file_path()):
        print("Error: Daemon is running. Use 'daemon stop' to stop it before running sync manually.")
        return 1

    lock_fd, error_message = acquire_sync_lock()
    if error_message:
        print(f"Error: {error_message}")
        return 1

    try:
        specific = getattr(config_obj, "specific_sync_jobs", None)
        paths_to_sync = specific or [
            key for key, value in config_obj._config.sync_jobs.items() if value.active
        ]
        if specific:
            invalid_jobs = [job for job in specific if job not in config_obj._config.sync_jobs]
            if invalid_jobs:
                print(f"Error: The following sync job(s) do not exist: {', '.join(invalid_jobs)}")
                return 1

        config_obj._config.dry_run = args.dry_run
        config_obj._config.force_resync = getattr(args, "force_resync", False)
        config_obj._config.force_operation = getattr(args, "force_operation", False)
        for key in paths_to_sync:
            perform_sync_operations(key)
        return 0
    finally:
        release_sync_lock(lock_fd)


def run_add_sync(args):
    """Add sync jobs to daemon queue. Returns 0 if all OK, 1 if any failed."""
    sync_jobs = getattr(args, "sync_jobs", [])
    errors = []
    for job in sync_jobs:
        response = request_add_sync(job)
        if response != "OK":
            errors.append(f"{job}: {response}")
    if errors:
        print(f"Error adding sync job(s): {'; '.join(errors)}")
        return 1
    print(f"Successfully added sync job(s): {', '.join(sync_jobs)}")
    return 0
