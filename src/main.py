#!/usr/bin/env python3

import os
import signal
import sys
import daemon
from config import load_config, parse_args, sync_jobs, specific_sync_jobs
from daemon_functions import daemon_main, stop_daemon, print_daemon_status
from sync import perform_sync_operations
from utils import check_tools, ensure_rclone_dir, handle_filter_changes, config_file, cache_dir, rclone_test_file_name
from logging_utils import log_message, log_error, ensure_log_file_path, setup_loggers
from shared_variables import signal_handler

# Initialize global variables
last_config_mtime = 0
exclusion_rules_file = None
force_resync = False


def main():
    global dry_run, daemon_mode
    args = parse_args()
    load_config()  # Load config first to set up log paths

    check_tools()
    ensure_rclone_dir()
    ensure_log_file_path()
    handle_filter_changes()

    log_message("Warning: This script does not prevent multiple instances from running. Please ensure you don't start it multiple times unintentionally.")

    # Log home directory
    home_dir = os.environ.get('HOME')
    if home_dir:
        log_message(f"Home directory: {home_dir}")
    else:
        log_error("Unable to determine home directory")

    if args.command == 'daemon':
        if args.action == 'start':
            try:
                log_message("Starting daemon...")
                with daemon.DaemonContext(
                    working_directory='/',
                    umask=0o002,
                    signal_map={
                        signal.SIGTERM: signal_handler,
                        signal.SIGINT: signal_handler,
                    },
                    stdout=sys.stdout,
                    stderr=sys.stderr
                ):
                    daemon_main()
            except Exception as e:
                log_error(f"Error starting daemon: {str(e)}")
                print(f"Error starting daemon: {str(e)}")
        elif args.action == 'stop':
            stop_daemon()
        elif args.action == 'status':
            print_daemon_status()
    elif args.command == 'sync':
        paths_to_sync = specific_sync_jobs if specific_sync_jobs else [
            key for key, value in sync_jobs.items() if value.get('active', True)]
        for key in paths_to_sync:
            if key in sync_jobs:
                perform_sync_operations(key)
            else:
                log_error(f"Specified sync job '{
                          key}' not found in configuration")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_error(f"Unhandled exception in main: {str(e)}")
        print(f"Unhandled exception: {str(e)}")


if __name__ == "__main__":
    main()
