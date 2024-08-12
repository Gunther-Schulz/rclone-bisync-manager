#!/usr/bin/env python3

import os
import signal
import sys
import daemon
from config import load_config, parse_args, sync_jobs, specific_sync_jobs
from daemon_functions import daemon_main, stop_daemon, print_daemon_status
from sync import perform_sync_operations
from utils import check_tools, ensure_rclone_dir, handle_filter_changes
from logging_utils import log_message, log_error, ensure_log_file_path, setup_loggers
from shared_variables import signal_handler


def main():
    try:
        # Load config first to set up log paths
        load_config()

        # Setup loggers
        setup_loggers()

        # Parse command-line arguments
        args = parse_args()

        # Setup signal handling
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

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
                with daemon.DaemonContext(
                    working_directory='/',
                    umask=0o002,
                    signal_map={
                        signal.SIGTERM: signal_handler,
                        signal.SIGINT: signal_handler,
                    }
                ):
                    daemon_main()
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
    except Exception as e:
        log_error(f"An unexpected error occurred: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
