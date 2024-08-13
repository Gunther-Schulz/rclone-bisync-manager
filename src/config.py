import yaml
import os
from datetime import datetime
import sys
from threading import Lock
from queue import Queue
import hashlib
from croniter import croniter
import json


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
        self.sync_schedules = {}
        self.script_start_time = datetime.now()
        self.last_config_mtime = 0
        self.redirect_rclone_log_output = False
        self.last_log_position = 0
        self.hash_warnings = {}
        self.sync_errors = {}
        self.run_missed_jobs = False
        self.run_initial_sync_on_startup = True

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

        self.load_last_sync_times()

    def validate_config(self):
        errors = []
        allowed_keys = {'local', 'rclone_remote',
                        'remote', 'schedule', 'active', 'dry_run'}
        for key, job in self.sync_jobs.items():
            if not all(field in job for field in ['local', 'rclone_remote', 'remote', 'schedule']):
                errors.append(f"Sync job '{
                              key}' is missing required fields (local, rclone_remote, remote, or schedule)")

            unrecognized_keys = set(job.keys()) - allowed_keys
            if unrecognized_keys:
                errors.append(f"Sync job '{key}' contains unrecognized keys: {
                              ', '.join(unrecognized_keys)}")

        if errors:
            raise ValueError("Configuration errors:\n" + "\n".join(errors))

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
        self.run_missed_jobs = config.get('run_missed_jobs', False)

        self.validate_config()  # Call validate_config after loading the configuration

        for key, value in self.sync_jobs.items():
            if value.get('active', True) and 'schedule' in value:
                self.sync_schedules[key] = croniter(value['schedule'])
            if key not in self.last_sync_times:
                self.last_sync_times[key] = None

        self.last_config_mtime = os.path.getmtime(self.config_file)

    def get_status_file_path(self, job_key):
        local_path = self.sync_jobs[job_key]['local']
        remote_path = f"{self.sync_jobs[job_key]['rclone_remote']}:{
            self.sync_jobs[job_key]['remote']}"
        unique_id = hashlib.md5(f"{job_key}:{local_path}:{
                                remote_path}".encode()).hexdigest()
        return os.path.join(self.cache_dir, f'{unique_id}.status')

    def save_last_sync_times(self):
        sync_times_file = os.path.join(self.cache_dir, 'last_sync_times.json')
        with open(sync_times_file, 'w') as f:
            json.dump({k: v.isoformat()
                      for k, v in self.last_sync_times.items()}, f)

    def load_last_sync_times(self):
        sync_times_file = os.path.join(self.cache_dir, 'last_sync_times.json')
        if os.path.exists(sync_times_file):
            with open(sync_times_file, 'r') as f:
                loaded_times = json.load(f)
                self.last_sync_times = {k: datetime.fromisoformat(
                    v) for k, v in loaded_times.items()}
        else:
            self.last_sync_times = {}

    def save_last_sync_times(self):
        sync_times_file = os.path.join(self.cache_dir, 'last_sync_times.json')
        with open(sync_times_file, 'w') as f:
            json.dump({k: v.isoformat()
                      for k, v in self.last_sync_times.items()}, f)

    def load_last_sync_times(self):
        sync_times_file = os.path.join(self.cache_dir, 'last_sync_times.json')
        if os.path.exists(sync_times_file):
            with open(sync_times_file, 'r') as f:
                loaded_times = json.load(f)
                self.last_sync_times = {k: datetime.fromisoformat(
                    v) for k, v in loaded_times.items()}
        else:
            self.last_sync_times = {}


config = Config()


def signal_handler(signum, frame):
    config.running = False
    config.shutting_down = True
    from logging_utils import log_message
    log_message('SIGINT or SIGTERM received. Initiating graceful shutdown.')
    print('SIGINT or SIGTERM received. Initiating graceful shutdown.')
    if hasattr(config, 'lock_fd'):
        config.lock_fd.close()
