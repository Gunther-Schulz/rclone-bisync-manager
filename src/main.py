#!/usr/bin/env python3

import os
import signal
import sys
import daemon
from config import config
from cli import parse_args
from daemon_functions import daemon_main, stop_daemon, print_daemon_status
from sync import perform_sync_operations
from utils import check_tools, ensure_rclone_dir, handle_filter_changes
from logging_utils import log_message, log_error, ensure_log_file_path, setup_loggers, log_config_file_location, set_config
from config import signal_handler
import fcntl


def check_and_create_lock_file():
    lock_file = '/tmp/rclone_bisync_manager.lock'
    try:
        lock_fd = open(lock_file, 'w')
        fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd
    except IOError:
        return None


def main():
    args = parse_args()
    config.load_config()  # Load config first to set up log paths
    set_config(config)  # Set the config for logging_utils
    ensure_log_file_path()

    config.daemon_mode = args.command == 'daemon'
    config.console_log = args.console_log
    config.dry_run = args.dry_run

    setup_loggers(config.console_log)
    log_config_file_location(config.config_file)

    check_tools()
    ensure_rclone_dir()
    handle_filter_changes()

    # Log home directory
    home_dir = os.environ.get('HOME')
    if home_dir:
        log_message(f"Home directory: {home_dir}")
    else:
        log_error("Unable to determine home directory")

    lock_file = '/tmp/rclone_bisync_manager.lock'

    if args.command == 'daemon':
        if args.action == 'start':
            if os.path.exists(lock_file):
                print("Error: Daemon is already running.")
                sys.exit(1)
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
        if os.path.exists(lock_file):
            print(
                "Error: Daemon is running. Use 'daemon stop' to stop it before running sync manually.")
            sys.exit(1)

        # Create a lock file for non-daemon mode
        lock_fd = open(lock_file, 'w')
        try:
            fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            print("Error: Another sync instance is already running.")
            sys.exit(1)

        try:
            if args.specific_sync_jobs:
                # Check if all provided sync job names exist
                invalid_jobs = [
                    job for job in args.specific_sync_jobs if job not in config.sync_jobs]
                if invalid_jobs:
                    print(f"Error: The following sync job(s) do not exist: {
                          ', '.join(invalid_jobs)}")
                    sys.exit(1)
                paths_to_sync = args.specific_sync_jobs
            else:
                paths_to_sync = [
                    key for key, value in config.sync_jobs.items() if value.get('active', True)]

            config.dry_run = args.dry_run
            config.force_resync = args.force_resync
            config.force_operation = args.force_operation
            for key in paths_to_sync:
                perform_sync_operations(key)
        finally:
            # Release the lock and remove the lock file
            fcntl.lockf(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            os.unlink(lock_file)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_error(f"Unhandled exception in main: {str(e)}")
        print(f"Unhandled exception: {str(e)}")
