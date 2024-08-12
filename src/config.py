import yaml
import os
from datetime import datetime
import sys
from threading import Lock
from queue import Queue
from interval_utils import parse_interval


def _initial_log_error(message):
    print(f"ERROR: {message}", file=sys.stderr)


class Config:
    def __init__(self):
        # Command line options
        self.dry_run = False
        self.force_resync = False
        self.console_log = False
        self.specific_sync_jobs = None
        self.force_operation = False

        # Daemon mode variables
        self.daemon_mode = False
        self.running = True
        self.shutting_down = False
        self.shutdown_complete = False
        self.currently_syncing = None
        self.current_sync_start_time = None
        self.sync_queue = Queue()
        self.queued_paths = set()
        self.sync_lock = Lock()

        # Sync operations
        self.local_base_path = None
        self.exclusion_rules_file = None
        self.sync_jobs = {}
        self.max_cpu_usage_percent = 100
        self.rclone_options = {}
        self.bisync_options = {}
        self.resync_options = {}
        self.last_sync_times = {}
        self.sync_intervals = {}
        self.script_start_time = datetime.now()
        self.last_config_mtime = 0
        self.redirect_rclone_log_output = False

        # File paths
        self.config_file = os.path.join(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser(
            '~/.config')), 'rclone-bisync-manager', 'config.yaml')
        self.cache_dir = os.path.join(os.environ.get(
            'XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'rclone-bisync-manager')
        self.rclone_test_file_name = "RCLONE_TEST"

        # Logging paths
        self.default_log_dir = os.path.join(os.environ.get(
            'XDG_STATE_HOME', os.path.expanduser('~/.local/state')), 'rclone-bisync-manager', 'logs')
        self.log_file_path = os.path.join(
            self.default_log_dir, 'rclone-bisync-manager.log')
        self.error_log_file_path = os.path.join(
            self.default_log_dir, 'rclone-bisync-manager-error.log')

    def load_config(self):
        if not os.path.exists(os.path.dirname(self.config_file)):
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        if not os.path.exists(self.config_file):
            error_message = f"Configuration file not found. Please ensure it exists at: {
                self.config_file}"
            _initial_log_error(error_message)
            sys.exit(1)

        with open(self.config_file, 'r') as f:
            config = yaml.safe_load(f)

        self.local_base_path = config.get('local_base_path')
        self.exclusion_rules_file = config.get('exclusion_rules_file', None)
        self.sync_jobs = config.get('sync_jobs', {})
        self.max_cpu_usage_percent = config.get('max_cpu_usage_percent', 100)
        self.rclone_options = config.get('rclone_options', {})
        self.bisync_options = config.get('bisync_options', {})
        self.resync_options = config.get('resync_options', {})
        self.redirect_rclone_log_output = config.get(
            'redirect_rclone_log_output', False)

        # Initialize last_sync_times and sync_intervals
        for key, value in self.sync_jobs.items():
            if value.get('active', True) and 'sync_interval' in value:
                if key not in self.last_sync_times:
                    self.last_sync_times[key] = self.script_start_time
                self.sync_intervals[key] = parse_interval(
                    value['sync_interval'])

        # Update last_config_mtime
        self.last_config_mtime = os.path.getmtime(self.config_file)


config = Config()


def signal_handler(signum, frame):
    config.running = False
    config.shutting_down = True
    from logging_utils import log_message
    log_message('SIGINT or SIGTERM received. Initiating graceful shutdown.')
    print('SIGINT or SIGTERM received. Initiating graceful shutdown.')
