#!/usr/bin/env python3

import os
import signal
import sys
import daemon
from rclone_bisync_manager.scheduler import scheduler
from rclone_bisync_manager.cli import parse_args
from rclone_bisync_manager.daemon_functions import daemon_main, stop_daemon, print_daemon_status
from rclone_bisync_manager.sync import perform_sync_operations
from rclone_bisync_manager.utils import check_tools, ensure_rclone_dir, handle_filter_changes, check_and_create_lock_file
from rclone_bisync_manager.logging_utils import log_message, log_error, ensure_log_file_path, setup_loggers, log_config_file_location, set_config
from rclone_bisync_manager.config import config, signal_handler
import fcntl
import traceback
import socket
import json


def main():
    args = parse_args()

    if args.config:
        config.set_config_file(args.config)
    else:
        config.set_config_file(config.default_config_file)

    print(f"Using config file: {config.config_file}")

    try:
        config.load_and_validate_config(args)
        print(f"Configuration loaded successfully from: {config.config_file}")
    except Exception as e:
        print(f"Error loading configuration: {str(e)}")
        sys.exit(1)

    if args.command == 'daemon':
        if args.action == 'start':
            try:
                print("Initializing daemon...")
                config.initialize_config(args)
                set_config(config)
                ensure_log_file_path()
                setup_loggers(args.console_log)
                log_config_file_location(config.config_file)
                log_message("Daemon initialization started")
                if hasattr(config, '_config') and config._config is not None and hasattr(config._config, 'log_file_path'):
                    print(f"Using log file: {config._config.log_file_path}")
                else:
                    print(
                        "Warning: Log file path not set or configuration not loaded properly.")
                print("Checking tools and directories...")
                check_tools()
                ensure_rclone_dir()
                handle_filter_changes()

                home_dir = os.environ.get('HOME')
                if not home_dir:
                    raise ValueError("Unable to determine home directory")

                print("Creating lock file...")
                lock_fd, error_message = check_and_create_lock_file()
                if error_message:
                    raise ValueError(f"Error: {error_message}")

                print("Starting daemon process...")
                log_message("Starting daemon in limbo state...")
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
                    config.args = args
                    print("Daemon process started. Calling daemon_main()...")
                    daemon_main()
            except Exception as e:
                error_trace = traceback.format_exc()
                log_error(f"Error starting daemon: {str(e)}\n{error_trace}")
                print(f"Error starting daemon: {
                      str(e)}\nFull traceback:\n{error_trace}")
                sys.exit(1)
        elif args.action == 'stop':
            stop_daemon()
        elif args.action == 'status':
            print_daemon_status()
        elif args.action == 'reload':
            socket_path = '/tmp/rclone_bisync_manager_status.sock'
            if not os.path.exists(socket_path):
                print("Daemon is not running.")
                return

            try:
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.connect(socket_path)
                client.sendall(b"RELOAD")
                chunks = []
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                response = b''.join(chunks).decode()
                client.close()
                print(response)
            except Exception as e:
                print(f"Error reloading daemon configuration: {e}")
    elif args.command == 'sync':
        if os.path.exists(config.LOCK_FILE_PATH):
            print(
                "Error: Daemon is running. Use 'daemon stop' to stop it before running sync manually.")
            sys.exit(1)

        # Create a lock file for non-daemon mode
        lock_fd = open(config.LOCK_FILE_PATH, 'w')
        try:
            fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            print("Error: Another sync instance is already running.")
            sys.exit(1)

        try:
            if args.specific_sync_jobs:
                invalid_jobs = [
                    job for job in args.specific_sync_jobs if job not in config._config.sync_jobs]
                if invalid_jobs:
                    print(f"Error: The following sync job(s) do not exist: {
                          ', '.join(invalid_jobs)}")
                    sys.exit(1)
                paths_to_sync = args.specific_sync_jobs
            else:
                paths_to_sync = [
                    key for key, value in config._config.sync_jobs.items() if value.active]

            config._config.dry_run = args.dry_run
            config._config.force_resync = args.force_resync
            config._config.force_operation = args.force_operation
            for key in paths_to_sync:
                perform_sync_operations(key)
        finally:
            # Release the lock and remove the lock file
            fcntl.lockf(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            os.unlink(config.LOCK_FILE_PATH)
    elif args.command == 'add-sync':
        add_sync_jobs(args.sync_jobs)


def add_sync_jobs(sync_jobs):
    socket_path = '/tmp/rclone_bisync_manager_add_sync.sock'
    if not os.path.exists(socket_path):
        print("Error: Daemon is not running.")
        return

    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(socket_path)
        client.sendall(json.dumps(sync_jobs).encode())
        response = client.recv(1024).decode()
        client.close()

        if response == "OK":
            print(f"Successfully added sync job(s): {', '.join(sync_jobs)}")
        else:
            print(f"Error adding sync job(s): {response}")
    except Exception as e:
        print(f"Error communicating with daemon: {str(e)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_error(f"Unhandled exception in main: {str(e)}")
        print(f"Unhandled exception: {str(e)}")
