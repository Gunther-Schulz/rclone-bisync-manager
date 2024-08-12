import yaml
import os
import argparse
from datetime import datetime
import sys

# Global variables
dry_run = False
force_resync = False
console_log = False
specific_sync_jobs = None
force_operation = False
daemon_mode = False
local_base_path = None
exclusion_rules_file = None
sync_jobs = {}
max_cpu_usage_percent = 100
rclone_options = {}
bisync_options = {}
resync_options = {}
last_sync_times = {}
script_start_time = datetime.now()
last_config_mtime = 0
rclone_test_file_name = "RCLONE_TEST"
cache_dir = os.path.join(os.environ.get(
    'XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'rclone-bisync-manager')

# Configuration file paths
config_file = os.path.join(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser(
    '~/.config')), 'rclone-bisync-manager', 'config.yaml')


def load_config():
    global local_base_path, exclusion_rules_file, sync_jobs, max_cpu_usage_percent, rclone_options, bisync_options, resync_options, last_sync_times

    if not os.path.exists(os.path.dirname(config_file)):
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
    if not os.path.exists(config_file):
        from logging_utils import log_error
        error_message = f"Configuration file not found. Please ensure it exists at: {
            config_file}"
        log_error(error_message)
        sys.exit(1)

    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)

    local_base_path = config.get('local_base_path')
    exclusion_rules_file = config.get('exclusion_rules_file', None)
    sync_jobs = config.get('sync_jobs', {})
    max_cpu_usage_percent = config.get('max_cpu_usage_percent', 100)
    rclone_options = config.get('rclone_options', {})
    bisync_options = config.get('bisync_options', {})
    resync_options = config.get('resync_options', {})

    # Initialize last_sync_times
    for key, value in sync_jobs.items():
        if value.get('active', True) and 'sync_interval' in value:
            if key not in last_sync_times:
                last_sync_times[key] = script_start_time

    # Initialize sync_intervals and last_sync_times
    sync_intervals = {key: parse_interval(
        value['sync_interval']) for key, value in sync_jobs.items() if 'sync_interval' in value}
    for key in sync_jobs:
        if key not in last_sync_times:
            last_sync_times[key] = script_start_time


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
