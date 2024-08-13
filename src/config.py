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
        self._init_command_line_options()
        self._init_daemon_variables()
        self._init_sync_operations()
        self._init_file_paths()
        self._init_logging_paths()
        self.load_last_sync_times()

    def _init_command_line_options(self):
        self.dry_run = False
        self.force_resync = False
        self.console_log = False
        self.specific_sync_jobs = None
        self.force_operation = False

    def _init_daemon_variables(self):
        self.daemon_mode = False
        self.running = True
        self.shutting_down = False
        self.shutdown_complete = False
        self.currently_syncing = None
        self.current_sync_start_time = None
        self.sync_queue = Queue()
        self.queued_paths = set()
        self.sync_lock = Lock()
        self.config_invalid = False

    def _init_sync_operations(self):
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

    def _init_file_paths(self):
        self.config_file = os.path.join(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser(
            '~/.config')), 'rclone-bisync-manager', 'config.yaml')
        self.cache_dir = os.path.join(os.environ.get(
            'XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'rclone-bisync-manager')
        self.rclone_test_file_name = "RCLONE_TEST"

    def _init_logging_paths(self):
        self.default_log_dir = os.path.join(os.environ.get(
            'XDG_STATE_HOME', os.path.expanduser('~/.local/state')), 'rclone-bisync-manager', 'logs')
        self.log_file_path = os.path.join(
            self.default_log_dir, 'rclone-bisync-manager.log')
        self.error_log_file_path = os.path.join(
            self.default_log_dir, 'rclone-bisync-manager-error.log')

    def load_config(self):
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_file}")

        with open(self.config_file, 'r') as f:
            config_data = yaml.safe_load(f)

        self._load_global_options(config_data)
        self._load_sync_jobs(config_data)
        self.validate_config()

    def _load_global_options(self, config_data):
        self.local_base_path = config_data.get('local_base_path')
        self.exclusion_rules_file = config_data.get(
            'exclusion_rules_file', None)
        self.max_cpu_usage_percent = config_data.get(
            'max_cpu_usage_percent', 100)
        self.rclone_options = config_data.get('rclone_options', {})
        self.bisync_options = config_data.get('bisync_options', {})
        self.resync_options = config_data.get('resync_options', {})
        self.redirect_rclone_log_output = config_data.get(
            'redirect_rclone_log_output', False)
        self.run_missed_jobs = config_data.get('run_missed_jobs', False)
        self.run_initial_sync_on_startup = config_data.get(
            'run_initial_sync_on_startup', True)

    def _load_sync_jobs(self, config_data):
        self.sync_jobs = config_data.get('sync_jobs', {})
        for key, value in self.sync_jobs.items():
            if value.get('active', True) and 'schedule' in value:
                self.sync_schedules[key] = croniter(value['schedule'])
            if key not in self.last_sync_times:
                self.last_sync_times[key] = None

        self.last_config_mtime = os.path.getmtime(self.config_file)

    def validate_config(self):
        errors = []
        errors.extend(self._validate_global_options())
        errors.extend(self._validate_sync_jobs())

        if errors:
            raise ValueError("Configuration errors:\n" + "\n".join(errors))

    def _get_global_allowed_keys(self):
        return {attr for attr in dir(self) if not attr.startswith('_') and attr not in self._get_sync_job_allowed_keys()}

    def _get_sync_job_allowed_keys(self):
        return {'local', 'rclone_remote', 'remote', 'schedule', 'active', 'dry_run',
                'rclone_options', 'bisync_options', 'resync_options'}

    def _validate_global_options(self):
        allowed_keys = self._get_global_allowed_keys()
        config_keys = set(yaml.safe_load(open(self.config_file)).keys())
        unrecognized_global_keys = config_keys - allowed_keys
        if unrecognized_global_keys:
            return [f"Unrecognized global options: {', '.join(unrecognized_global_keys)}"]
        return []

    def _validate_sync_jobs(self):
        allowed_keys = self._get_sync_job_allowed_keys()
        errors = []
        for key, job in self.sync_jobs.items():
            if not all(field in job for field in ['local', 'rclone_remote', 'remote', 'schedule']):
                errors.append(f"Sync job '{
                              key}' is missing required fields (local, rclone_remote, remote, or schedule)")

            unrecognized_keys = set(job.keys()) - allowed_keys
            if unrecognized_keys:
                errors.append(f"Sync job '{key}' contains unrecognized keys: {
                              ', '.join(unrecognized_keys)}")

            if 'schedule' in job:
                try:
                    croniter(job['schedule'])
                except ValueError as e:
                    errors.append(f"Invalid cron string for sync job '{
                                  key}': {str(e)}")

        return errors

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


config = Config()


def signal_handler(signum, frame):
    config.running = False
    config.shutting_down = True
    from logging_utils import log_message
    log_message('SIGINT or SIGTERM received. Initiating graceful shutdown.')
    print('SIGINT or SIGTERM received. Initiating graceful shutdown.')
    if hasattr(config, 'lock_fd'):
        config.lock_fd.close()
