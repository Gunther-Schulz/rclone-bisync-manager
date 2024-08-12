import yaml
import os
from datetime import datetime
import sys
from interval_utils import parse_interval
from logging_utils import log_error

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

sync_intervals = {}


def load_config():
    global local_base_path, exclusion_rules_file, sync_jobs, max_cpu_usage_percent, rclone_options, bisync_options, resync_options, last_sync_times, last_config_mtime, sync_intervals

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
    max_cpu_usage_percent = config.get('max_cpu_usage_percent', 100)
    rclone_options = config.get('rclone_options', {})
    bisync_options = config.get('bisync_options', {})
    resync_options = config.get('resync_options', {})

    # Initialize last_sync_times and sync_intervals
    for key, value in sync_jobs.items():
        if value.get('active', True) and 'sync_interval' in value:
            if key not in last_sync_times:
                last_sync_times[key] = script_start_time
            sync_intervals[key] = parse_interval(value['sync_interval'])

    # Update last_config_mtime
    last_config_mtime = os.path.getmtime(config_file)
