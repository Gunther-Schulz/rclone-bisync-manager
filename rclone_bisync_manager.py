#!/usr/bin/env python3

import yaml
import os
import sys
import hashlib
import subprocess
import argparse
from datetime import datetime, timedelta
import signal
import time
import daemon
import json
import socket
import threading
import heapq
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from queue import Queue
from threading import Lock

# Note: Send a SIGINT twice to force exit

# Set the locale to UTF-8 to handle special characters correctly
os.environ['LC_ALL'] = 'C.UTF-8'

# Global variables for the command line options
dry_run = False
force_resync = False
console_log = False
specific_sync_jobs = None

# Default log directory
default_log_dir = os.path.join(os.environ.get('XDG_STATE_HOME', os.path.expanduser(
    '~/.local/state')), 'rclone-bisync-manager', 'logs')
# Log file path
log_file_path = os.path.join(default_log_dir, 'rclone-bisync-manager.log')
# Error log file path
error_log_file_path = os.path.join(
    default_log_dir, 'rclone-bisync-manager-error.log')
# Global variables for the PID file
pid_file = os.path.join(os.environ.get(
    'XDG_RUNTIME_DIR', '/tmp'), 'rclone-bisync-manager.pid')
# Global variables for the config file
config_file = os.path.join(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser(
    '~/.config')), 'rclone-bisync-manager', 'config.yaml')
# Global variables for the cache directory
cache_dir = os.path.join(os.environ.get(
    'XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'rclone-bisync-manager')
# Global variables for the resync status file
resync_status_file_name = ".resync_status"
# Global variables for the bisync status file
bisync_status_file_name = ".bisync_status"
# Global variables for the log files
sync_log_file_name = "rclone-bisync-manager.log"
# Global variables for the error log file
sync_error_log_file_name = "rclone-bisync-manager-error.log"
# Global variables for the rclone test file.
rclone_test_file_name = "RCLONE_TEST"
# Global counter for CTRL-C presses
ctrl_c_presses = 0
# Global list to keep track of subprocesses
subprocesses = []
# Global variables for the daemon mode
daemon_mode = False
# Global variables for the sync intervals
sync_intervals = {}
# Global variables for the last sync times
last_sync_times: Dict[str, datetime] = {}
# Global variable for the script start time
script_start_time = datetime.now()
# Global variable to track the last modification time of the config file
last_config_mtime = 0
# Global variable for the lock file
lock_file = None
# Global variables for the sync queue
sync_queue = Queue()
# Global variables for the sync queue
queued_paths = set()
# Global variables for the sync lock
sync_lock = Lock()
# Global variables for the currently syncing path
currently_syncing = None
# Global variables for the currently syncing path
current_sync_start_time = None
# Global variable to indicate whether the daemon should continue running
running = True
# Global variable to indicate whether the daemon is shutting down
shutting_down = False
# Global variable to indicate whether the daemon has completed shutting down
shutdown_complete = False


def signal_handler(signum, frame):
    global ctrl_c_presses, shutting_down
    ctrl_c_presses += 1

    if ctrl_c_presses > 1:
        log_message('Multiple SIGINT detected. Forcing exit.')
        print('Multiple CTRL-C detected. Forcing exit.')
        os._exit(1)  # Force exit immediately

    log_message('SIGINT or SIGTERM received. Initiating graceful shutdown.')

    # Set the shutting_down flag
    shutting_down = True


# Set the signal handler
signal.signal(signal.SIGINT, signal_handler)


# Logging
def log_message(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"{timestamp} - {message}\n"
    with open(log_file_path, 'a') as f:
        f.write(log_entry)
    if console_log:
        print(log_entry, end='')


# Logging errors
def log_error(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    error_entry = f"{timestamp} - ERROR: {message}\n"
    with open(log_file_path, 'a') as f:
        f.write(error_entry)
    with open(error_log_file_path, 'a') as f:
        f.write(f"{timestamp} - {message}\n")
    if console_log:
        print(error_entry, end='')


# Load the configuration file
def load_config():
    global local_base_path, exclusion_rules_file, sync_jobs, max_cpu_usage_percent, rclone_options, bisync_options, resync_options, sync_intervals, last_sync_times
    if not os.path.exists(os.path.dirname(config_file)):
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
    if not os.path.exists(config_file):
        error_message = f"Configuration file not found. Please ensure it exists at: {
            config_file}"
        log_error(error_message)
        sys.exit(1)
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    local_base_path = config.get('local_base_path')
    exclusion_rules_file = config.get('exclusion_rules_file', None)
    sync_jobs = config.get('sync_jobs', {})

    # Ensure the log directory exists
    os.makedirs(default_log_dir, exist_ok=True)

    max_cpu_usage_percent = config.get('max_cpu_usage_percent', 100)
    rclone_options = config.get('rclone_options', {})
    bisync_options = config.get('bisync_options', {})
    resync_options = config.get('resync_options', {})

    # Initialize last_sync_times but don't schedule tasks yet
    for key, value in sync_jobs.items():
        if value.get('active', True) and 'sync_interval' in value:
            if key not in last_sync_times:
                last_sync_times[key] = script_start_time


# Parse interval string to seconds
def parse_interval(interval_str):
    interval_str = interval_str.lower()
    if interval_str == 'hourly':
        return 3600  # 1 hour in seconds
    elif interval_str == 'daily':
        return 86400  # 24 hours in seconds
    elif interval_str == 'weekly':
        return 604800  # 7 days in seconds
    elif interval_str == 'monthly':
        return 2592000  # 30 days in seconds (approximate)
    elif interval_str == 'yearly':
        return 31536000  # 365 days in seconds (approximate)

    unit = interval_str[-1].lower()
    try:
        value = int(interval_str[:-1])
    except ValueError:
        raise ValueError(f"Invalid interval format: {interval_str}")

    if unit == 'm':
        return value * 60
    elif unit == 'h':
        return value * 3600
    elif unit == 'd':
        return value * 86400
    elif unit == 'w':
        return value * 604800
    elif unit == 'y':
        return value * 31536000
    else:
        raise ValueError(f"Invalid interval format: {interval_str}")


# Parse command line arguments
def parse_args():
    parser = argparse.ArgumentParser(description="RClone BiSync Manager")
    parser.add_argument('-d', '--dry-run', action='store_true',
                        help='Perform a dry run without making any changes.')
    parser.add_argument('--console-log', action='store_true',
                        help='Print log messages to the console in addition to the log files.')

    subparsers = parser.add_subparsers(dest='command', required=True)

    # Daemon command
    daemon_parser = subparsers.add_parser('daemon', help='Run in daemon mode')
    daemon_parser.add_argument('action', choices=['start', 'stop', 'status'],
                               help='Action to perform on the daemon')

    # Sync command
    sync_parser = subparsers.add_parser(
        'sync', help='Perform a sync operation')
    sync_parser.add_argument('sync_jobs', nargs='*',
                             help='Specify sync jobs to run (optional, run all active jobs if not specified)')
    sync_parser.add_argument('--resync', action='store_true',
                             help='Force a resynchronization, ignoring previous sync status.')
    sync_parser.add_argument('--force-bisync', action='store_true',
                             help='Force the bisync operation without confirmation.')

    args = parser.parse_args()

    global dry_run, force_resync, console_log, specific_sync_jobs, force_operation, daemon_mode
    dry_run = args.dry_run
    console_log = args.console_log

    if args.command == 'sync':
        force_resync = args.resync
        specific_sync_jobs = args.sync_jobs if args.sync_jobs else None
        force_operation = args.force_bisync
        daemon_mode = False
    elif args.command == 'daemon':
        force_resync = False
        specific_sync_jobs = None
        force_operation = False
        daemon_mode = True

    return args


# Check if the required tools are installed
def check_tools():
    required_tools = ["rclone"]
    for tool in required_tools:
        if subprocess.call(['which', tool], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            error_message = f"{tool} could not be found, please install it."
            log_error(error_message)
            sys.exit(1)


# Add a new function to check if cpulimit is installed
def is_cpulimit_installed():
    return subprocess.call(['which', 'cpulimit'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


# Ensure the rclone directory exists.
def ensure_rclone_dir():
    rclone_dir = os.path.join(os.environ['HOME'], '.cache', 'rclone', 'bisync')
    if not os.access(rclone_dir, os.W_OK):
        os.makedirs(rclone_dir, exist_ok=True)
        os.chmod(rclone_dir, 0o777)


# Ensure log file path exists
def ensure_log_file_path():
    os.makedirs(default_log_dir, exist_ok=True)


# Calculate the MD5 of a file
def calculate_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


# Handle filter changes
def handle_filter_changes():
    stored_md5_file = os.path.join(cache_dir, '.filter_md5')
    os.makedirs(cache_dir, exist_ok=True)  # Ensure cache directory exists
    if os.path.exists(exclusion_rules_file):
        current_md5 = calculate_md5(exclusion_rules_file)
        if os.path.exists(stored_md5_file):
            with open(stored_md5_file, 'r') as f:
                stored_md5 = f.read().strip()
        else:
            stored_md5 = ""
        if current_md5 != stored_md5:
            with open(stored_md5_file, 'w') as f:
                f.write(current_md5)
            log_message("Filter file has changed. A resync is required.")
            global force_resync
            force_resync = True


# Handle the exit code of rclone
def handle_rclone_exit_code(result_code, local_path, sync_type):
    messages = {
        0: "completed successfully",
        1: "Non-critical error. A rerun may be successful.",
        2: "Critically aborted, please check the logs for more information.",
        3: "Directory not found, please check the logs for more information.",
        4: "File not found, please check the logs for more information.",
        5: "Temporary error. More retries might fix this issue.",
        6: "Less serious errors, please check the logs for more information.",
        7: "Fatal error, please check the logs for more information.",
        8: "Transfer limit exceeded, please check the logs for more information.",
        9: "successful but no files were transferred.",
        10: "Duration limit exceeded, please check the logs for more information."
    }
    message = messages.get(
        result_code, f"failed with an unknown error code {result_code}, please check the logs for more information.")
    if result_code == 0 or result_code == 9:
        log_message(f"{sync_type} {message} for {local_path}.")
        return "COMPLETED"
    else:
        log_error(f"{sync_type} {message} for {local_path}.")
        return "FAILED"

# Add rclone arguments


def add_rclone_args(rclone_args, options):
    for key, value in options.items():
        option_key = key.replace('_', '-')
        if value is None:
            rclone_args.append(f'--{option_key}')
        elif isinstance(value, bool):
            if value:
                rclone_args.append(f'--{option_key}')
        elif isinstance(value, list):
            for item in value:
                rclone_args.extend([f'--{option_key}', str(item)])
        else:
            rclone_args.extend([f'--{option_key}', str(value)])


# Get base rclone options
def get_base_rclone_options():
    options = {
        'exclude': [resync_status_file_name, bisync_status_file_name],
        'log-file': log_file_path,
        'log-level': rclone_options['log_level'] if not dry_run else 'ERROR',
        'recover': None,
        'resilient': None,
    }

    # Note: 'resync', 'log-file', 'recover', and 'resilient' options are set internally and cannot be overridden by user configuration

    # Add all options from rclone_options
    for key, value in rclone_options.items():
        if key in ['resync', 'log_file', 'recover', 'resilient']:
            continue  # Skip these options as they are set internally

        # Convert snake_case to kebab-case for rclone options
        option_key = key.replace('_', '-')

        if value is None:
            # For options without values, we just include the key
            options[option_key] = None
        else:
            # Convert all other values to strings
            options[option_key] = str(value)

    return options


# Perform a bisync
def bisync(remote_path, local_path, path_dry_run):
    log_message(f"Bisync started for {local_path} at {
                datetime.now()}" + (" - Performing a dry run" if path_dry_run else ""))

    rclone_args = [
        'rclone', 'bisync', remote_path, local_path,
    ]

    # Get base options and add bisync-specific options
    default_options = get_base_rclone_options()
    default_options.update(bisync_options)

    # Override default options with user-defined options
    combined_options = {**default_options, **rclone_options}

    # Add options to rclone_args
    add_rclone_args(rclone_args, combined_options)

    if os.path.exists(exclusion_rules_file):
        rclone_args.extend(['--exclude-from', exclusion_rules_file])
    if path_dry_run:
        rclone_args.append('--dry-run')
    if force_operation:
        rclone_args.append('--force')

    # Only use cpulimit if it's installed
    if is_cpulimit_installed():
        cpulimit_command = ['cpulimit', '--limit=' +
                            str(max_cpu_usage_percent), '--']
        cpulimit_command.extend(rclone_args)
        result = subprocess.run(
            cpulimit_command, capture_output=True, text=True)
    else:
        result = subprocess.run(rclone_args, capture_output=True, text=True)

    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Bisync")
    log_message(f"Bisync status for {local_path}: {sync_result}")
    write_sync_status(local_path, sync_result)


# Perform a resync
def resync(remote_path, local_path, path_dry_run):
    if force_resync:
        log_message("Force resync requested.")
    else:
        sync_status = read_resync_status(local_path)
        if sync_status == "COMPLETED":
            log_message("No resync necessary. Skipping.")
            return sync_status
        elif sync_status == "IN_PROGRESS":
            log_message("Resuming interrupted resync.")
        elif sync_status == "FAILED":
            log_error(
                f"Previous resync failed. Manual intervention required. Status: {sync_status}. Check the logs at {log_file_path} to fix the issue and remove the file {os.path.join(local_path, resync_status_file_name)} to start a new resync. Exiting...")
            sys.exit(1)

    log_message(f"Resync started for {local_path} at {
                datetime.now()}" + (" - Performing a dry run" if path_dry_run else ""))

    write_resync_status(local_path, "IN_PROGRESS")

    rclone_args = [
        'rclone', 'bisync', remote_path, local_path,
        '--resync',
    ]

    # Get base options and add resync-specific options
    default_options = get_base_rclone_options()
    default_options.update(resync_options)

    # Override default options with user-defined options
    combined_options = {**default_options, **rclone_options}

    # Add options to rclone_args
    add_rclone_args(rclone_args, combined_options)

    if os.path.exists(exclusion_rules_file):
        rclone_args.extend(['--exclude-from', exclusion_rules_file])
    if path_dry_run:
        rclone_args.append('--dry-run')

    # Only use cpulimit if it's installed
    if is_cpulimit_installed():
        cpulimit_command = ['cpulimit', '--limit=' +
                            str(max_cpu_usage_percent), '--']
        cpulimit_command.extend(rclone_args)
        result = subprocess.run(
            cpulimit_command, capture_output=True, text=True)
    else:
        result = subprocess.run(rclone_args, capture_output=True, text=True)

    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Resync")
    log_message(f"Resync status for {local_path}: {sync_result}")
    write_resync_status(local_path, sync_result)

    return sync_result


# Write the sync status
def write_sync_status(local_path, sync_status):
    sync_status_file = os.path.join(local_path, bisync_status_file_name)
    if not dry_run:
        with open(sync_status_file, 'w') as f:
            f.write(sync_status)


# Write the resync status
def write_resync_status(local_path, sync_status):
    sync_status_file = os.path.join(local_path, resync_status_file_name)
    if not dry_run:
        with open(sync_status_file, 'w') as f:
            f.write(sync_status)


# Read the resync status
def read_resync_status(local_path):
    sync_status_file = os.path.join(local_path, resync_status_file_name)
    if os.path.exists(sync_status_file):
        with open(sync_status_file, 'r') as f:
            return f.read().strip()
    return "NONE"


# Ensure the local directory exists. If not, create it.
def ensure_local_directory(local_path):
    if not os.path.exists(local_path):
        os.makedirs(local_path)
        log_message(f"Local directory {local_path} created.")


# Check if the local rclone test file exists
def check_local_rclone_test(local_path):
    # use rclone lsf to check if the file exists
    result = subprocess.run(['rclone', 'lsf', local_path],
                            capture_output=True, text=True)
    if not rclone_test_file_name in result.stdout:
        log_message(f"{rclone_test_file_name} file not found in {
                    local_path}. To add it run 'rclone touch \"{local_path}/{rclone_test_file_name}\"'")
        return False
    return True


# Check if the remote rclone test file exists
def check_remote_rclone_test(remote_path):
    # use rclone lsf to check if the file exists
    result = subprocess.run(['rclone', 'lsf', remote_path],
                            capture_output=True, text=True)
    if not rclone_test_file_name in result.stdout:
        log_message(f"{rclone_test_file_name} file not found in {
                    remote_path}. To add it run 'rclone touch \"{remote_path}/{rclone_test_file_name}\"'")
        return False
    return True


# Define a dataclass for the sync task
@dataclass(order=True)
class SyncTask:
    scheduled_time: datetime
    path_key: str = field(compare=False)


# Define a class for the sync scheduler
class SyncScheduler:
    def __init__(self):
        self.tasks: List[SyncTask] = []
        self.task_map: Dict[str, SyncTask] = {}

    def schedule_task(self, path_key: str, next_run: datetime):
        if path_key in self.task_map:
            self.remove_task(path_key)
        task = SyncTask(next_run, path_key)
        heapq.heappush(self.tasks, task)
        self.task_map[path_key] = task

    def remove_task(self, path_key: str):
        if path_key in self.task_map:
            task = self.task_map.pop(path_key)
            self.tasks.remove(task)
            heapq.heapify(self.tasks)

    def get_next_task(self) -> Optional[SyncTask]:
        return self.tasks[0] if self.tasks else None

    def pop_next_task(self) -> Optional[SyncTask]:
        if self.tasks:
            task = heapq.heappop(self.tasks)
            del self.task_map[task.path_key]
            return task
        return None


scheduler = SyncScheduler()


# Reload the configuration
def reload_config():
    global dry_run, last_sync_times
    log_message("Reloading configuration...")

    old_sync_jobs = sync_jobs.copy()
    old_intervals = {key: parse_interval(
        value['sync_interval']) for key, value in old_sync_jobs.items() if 'sync_interval' in value}

    load_config()
    args = parse_args()
    dry_run = args.dry_run

    current_time = datetime.now()

    # Update existing tasks and add new ones
    for key, value in sync_jobs.items():
        if value.get('active', True) and 'sync_interval' in value:
            new_interval = parse_interval(value['sync_interval'])
            if key in old_intervals:
                old_interval = old_intervals[key]
                last_sync = last_sync_times[key]
                time_since_last_sync = current_time - last_sync
                old_progress = time_since_last_sync.total_seconds() / old_interval

                # Calculate the next sync time based on the new interval
                next_sync = last_sync + \
                    timedelta(seconds=new_interval * old_progress)

                # If the next sync time is in the past, schedule it for the next interval
                if next_sync <= current_time:
                    next_sync = current_time + timedelta(seconds=new_interval)

                scheduler.schedule_task(key, next_sync)
            else:
                # For new paths, schedule the first sync after one interval
                next_sync = current_time + timedelta(seconds=new_interval)
                last_sync_times[key] = current_time
                scheduler.schedule_task(key, next_sync)

    # Remove tasks for paths that no longer exist
    for key in old_sync_jobs:
        if key not in sync_jobs:
            scheduler.remove_task(key)
            if key in last_sync_times:
                del last_sync_times[key]

    log_message(f"Configuration reloaded. Dry run: {dry_run}")
    log_message(f"Updated sync intervals: {sync_intervals}")
    log_message(f"Adjusted last sync times: {last_sync_times}")


# Daemon main function
def daemon_main():
    global running, dry_run, last_sync_times, currently_syncing, queued_paths, shutting_down, shutdown_complete

    log_message("Daemon started")

    load_config()

    status_thread = threading.Thread(target=status_server, daemon=True)
    status_thread.start()

    # Perform initial sync for all active paths
    log_message("Starting initial sync for all active sync jobs")
    for key, value in sync_jobs.items():
        if value.get('active', True):
            add_to_sync_queue(key)

    while running and not shutting_down:
        try:
            # Process the sync queue
            while not sync_queue.empty() and not shutting_down:
                with sync_lock:
                    if currently_syncing is None:
                        key = sync_queue.get_nowait()
                        currently_syncing = key
                        queued_paths.remove(key)
                    else:
                        break  # Exit the loop if a sync is already in progress

                if key in sync_jobs:
                    perform_sync_operations(key)

                with sync_lock:
                    currently_syncing = None

            # Check for scheduled tasks
            next_task = scheduler.get_next_task()
            if next_task and not shutting_down:
                now = datetime.now()
                if now >= next_task.scheduled_time:
                    task = scheduler.pop_next_task()
                    add_to_sync_queue(task.path_key)
                else:
                    # Sleep until the next task or for a maximum of 1 second
                    sleep_time = min(
                        (next_task.scheduled_time - now).total_seconds(), 1)
                    time.sleep(sleep_time)
            else:
                time.sleep(1)

            if check_config_changed() and not shutting_down:
                reload_config()

        except Exception as e:
            log_error(f"An error occurred in the main loop: {str(e)}")
            time.sleep(1)  # Avoid tight loop in case of persistent errors

    # Graceful shutdown
    log_message('Daemon shutting down...')

    # Wait for current sync to finish
    while currently_syncing:
        time.sleep(1)

    # Clear remaining queue
    while not sync_queue.empty():
        sync_queue.get_nowait()
    queued_paths.clear()

    shutdown_complete = True
    log_message('Daemon shutdown complete.')
    status_thread.join(timeout=5)


# Add a path to the sync queue
def add_to_sync_queue(key):
    global shutting_down
    with sync_lock:
        if not shutting_down and key not in queued_paths and key != currently_syncing:
            sync_queue.put(key)
            queued_paths.add(key)


# Perform the sync operations
def perform_sync_operations(key):
    global current_sync_start_time
    current_sync_start_time = datetime.now()

    value = sync_jobs[key]

    local_path = os.path.join(local_base_path, value['local'])
    remote_path = f"{value['rclone_remote']}:{value['remote']}"

    if not check_local_rclone_test(local_path) or not check_remote_rclone_test(remote_path):
        current_sync_start_time = None
        return

    ensure_local_directory(local_path)

    path_dry_run = dry_run or value.get('dry_run', False)

    if resync(remote_path, local_path, path_dry_run) == "COMPLETED":
        bisync(remote_path, local_path, path_dry_run)

    # Update last sync time and schedule next run
    last_sync_times[key] = datetime.now()
    interval = parse_interval(value['sync_interval'])
    next_run = last_sync_times[key] + timedelta(seconds=interval)
    scheduler.schedule_task(key, next_run)

    current_sync_start_time = None


# Generate the status report
def generate_status_report():
    current_time = datetime.now()
    status = {
        "pid": os.getpid(),
        "active_syncs": {},
        "last_check": current_time.isoformat(),
        "global_dry_run": dry_run,
        "currently_syncing": currently_syncing,
        "sync_queue_size": sync_queue.qsize(),
        "queued_paths": list(queued_paths),
        "shutting_down": shutting_down
    }

    if currently_syncing and current_sync_start_time:
        sync_duration = current_time - current_sync_start_time
        status["current_sync_duration"] = str(sync_duration).split('.')[
            0]  # Remove microseconds

    for key, value in sync_jobs.items():
        local_path = os.path.join(local_base_path, value['local'])
        remote_path = f"{value['rclone_remote']}:{value['remote']}"

        last_sync = last_sync_times.get(key, "Never")
        if isinstance(last_sync, datetime):
            last_sync = last_sync.isoformat()

        status["active_syncs"][key] = {
            "local_path": local_path,
            "remote_path": remote_path,
            "sync_interval": value.get('sync_interval', "Not set"),
            "last_sync": last_sync,
            "dry_run": dry_run or value.get('dry_run', False),
            "is_active": value.get('active', True),
            "is_currently_syncing": key == currently_syncing,
        }

        if key == currently_syncing and current_sync_start_time:
            sync_duration = current_time - current_sync_start_time
            status["active_syncs"][key]["current_sync_duration"] = str(
                sync_duration).split('.')[0]  # Remove microseconds

    return json.dumps(status, ensure_ascii=False, indent=2)


# Read the sync status
def read_sync_status(local_path):
    sync_status_file = os.path.join(local_path, bisync_status_file_name)
    if os.path.exists(sync_status_file):
        with open(sync_status_file, 'r') as f:
            return f.read().strip()
    return "UNKNOWN"


# Handle the status request
def handle_status_request(conn):
    status = generate_status_report()
    conn.sendall(status.encode())
    conn.close()


# Start the status server
def status_server():
    global running, shutdown_complete
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    socket_path = '/tmp/rclone_bisync_manager_status.sock'

    try:
        os.unlink(socket_path)
    except OSError:
        if os.path.exists(socket_path):
            raise

    server.bind(socket_path)
    server.listen(1)
    server.settimeout(1)  # Set a timeout so we can check the running flag

    while running or not shutdown_complete:
        try:
            conn, addr = server.accept()
            threading.Thread(target=handle_status_request,
                             args=(conn,)).start()
        except socket.timeout:
            continue

    server.close()
    os.unlink(socket_path)


# Check if the config file has changed
def check_config_changed():
    global last_config_mtime
    try:
        current_mtime = os.path.getmtime(config_file)
        if current_mtime > last_config_mtime:
            last_config_mtime = current_mtime
            return True
    except OSError:
        pass  # File doesn't exist or can't be accessed
    return False


# Stop the daemon
def stop_daemon():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    if os.path.exists(socket_path):
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(socket_path)
            status = json.loads(client.recv(4096).decode())
            client.close()

            if 'pid' in status:
                os.kill(status['pid'], signal.SIGTERM)
                print(f"Sent SIGTERM to daemon (PID: {status['pid']})")
                print("Daemon is shutting down. Use 'daemon status' to check progress.")

                # Log the stop request
                log_message("Daemon stop request received. Shutting down.")
            else:
                print("Unable to determine daemon PID from status")
        except Exception as e:
            print(f"Error stopping daemon: {e}")
    else:
        print("Status socket not found. Daemon may not be running.")


def print_daemon_status():
    # Define the socket path
    socket_path = '/tmp/rclone_bisync_manager_status.sock'

    # Check if the socket path exists
    if os.path.exists(socket_path):
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(socket_path)
            status = json.loads(client.recv(4096).decode())
            client.close()

            if status.get("shutting_down", False):
                print("Daemon is shutting down. Current status:")
            print(json.dumps(status, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"Error getting daemon status: {e}")
    else:
        print("Daemon is not running.")


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


if __name__ == "__main__":
    main()
