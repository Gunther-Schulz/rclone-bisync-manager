import yaml
import os
from datetime import datetime
from threading import Lock
from queue import Queue
import hashlib
from croniter import croniter
import json
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, field_validator


class SyncJobConfig(BaseModel):
    local: str
    rclone_remote: str
    remote: str
    schedule: str
    active: bool = True
    dry_run: bool = False
    rclone_options: Dict[str, Any] = {}
    bisync_options: Dict[str, Any] = {}
    resync_options: Dict[str, Any] = {}

    @field_validator('schedule')
    @classmethod
    def validate_cron(cls, v):
        try:
            croniter(v)
        except ValueError as e:
            raise ValueError(f"Invalid cron string: {str(e)}")
        return v


class ConfigSchema(BaseModel):
    local_base_path: str
    exclusion_rules_file: Optional[str] = None
    max_cpu_usage_percent: int = 100
    redirect_rclone_log_output: bool = False
    run_missed_jobs: bool = False
    run_initial_sync_on_startup: bool = True
    rclone_options: Dict[str, Any] = {}
    bisync_options: Dict[str, Any] = {}
    resync_options: Dict[str, Any] = {}
    sync_jobs: Dict[str, SyncJobConfig]
    dry_run: bool = False
    force_resync: bool = False
    console_log: bool = False
    specific_sync_jobs: Optional[List[str]] = None
    force_operation: bool = False
    daemon_mode: bool = False

    @field_validator('max_cpu_usage_percent')
    @classmethod
    def check_cpu_usage(cls, v):
        if v < 0 or v > 100:
            raise ValueError('max_cpu_usage_percent must be between 0 and 100')
        return v

    @field_validator('sync_jobs')
    @classmethod
    def validate_sync_jobs(cls, v):
        errors = []
        for key, job in v.items():
            try:
                if isinstance(job, dict):
                    SyncJobConfig(**job)
                elif not isinstance(job, SyncJobConfig):
                    raise ValueError(f"Invalid type for sync job '{
                                     key}': expected dict or SyncJobConfig")
            except ValueError as e:
                for error in e.errors():
                    field = error['loc'][0]
                    msg = error['msg']
                    if field == 'schedule' and msg == 'Field required':
                        errors.append(f"Sync job '{
                                      key}' is missing the required 'schedule' field. Please add a valid cron schedule.")
                    else:
                        errors.append(f"Invalid configuration for sync job '{
                                      key}': {field} - {msg}")

        # Check for invalid fields
        for key, job in v.items():
            if isinstance(job, dict):
                invalid_fields = set(job.keys()) - \
                    set(SyncJobConfig.model_fields.keys())
                if invalid_fields:
                    errors.append(f"Sync job '{key}' contains invalid fields: {
                                  ', '.join(invalid_fields)}")

        if errors:
            raise ValueError("\n".join(errors))
        return v


class Config:
    def __init__(self):
        self._config: Optional[ConfigSchema] = None
        self.args = None
        self._init_file_paths()
        self._init_logging_paths()
        self.last_sync_times = {}
        self.load_last_sync_times()
        self.sync_queue = Queue()
        self.queued_paths = set()
        self.sync_lock = Lock()
        self.currently_syncing = None
        self.current_sync_start_time = None
        self.running = True
        self.shutting_down = False
        self.shutdown_complete = False
        self.config_invalid = False

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

    def load_config(self, args):
        self.args = args  # Store the args
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_file}")

        with open(self.config_file, 'r') as f:
            config_data = yaml.safe_load(f)

        # Update config_data with command-line arguments
        config_data.update({
            'dry_run': args.dry_run,
            'force_resync': args.force_resync,
            'console_log': args.console_log,
            'specific_sync_jobs': args.specific_sync_jobs,
            'force_operation': args.force_operation,
            'daemon_mode': args.daemon_mode
        })

        try:
            self._config = ConfigSchema(**config_data)
            errors = self._validate_sync_jobs()
            if errors:
                raise ValueError("\n".join(errors))
        except ValueError as e:
            error_messages = []
            for error in e.errors():
                field = '.'.join(error['loc'])
                msg = error['msg']
                error_messages.append(f"Error in {field}: {msg}")
            raise ValueError("\n".join(error_messages))

        self.validate_config()

    def validate_config(self):
        errors = []
        errors.extend(self._validate_global_options())
        errors.extend(self._validate_sync_jobs())

        if errors:
            raise ValueError("Configuration errors:\n" +
                             "\n".join(f"- {error}" for error in errors))

    def _get_global_allowed_keys(self):
        return set(ConfigSchema.model_fields.keys())

    def _get_shared_allowed_keys(self):
        return {'rclone_options', 'bisync_options', 'resync_options'}

    def _validate_global_options(self):
        allowed_keys = self._get_global_allowed_keys() | self._get_shared_allowed_keys()
        config_keys = set(self._config.model_dump(
            exclude={'sync_jobs'}).keys())
        unrecognized_global_keys = config_keys - allowed_keys
        if unrecognized_global_keys:
            return [f"Unrecognized global options: {', '.join(unrecognized_global_keys)}"]
        return []

    def _validate_sync_jobs(self):
        errors = []
        for key, job in self._config.sync_jobs.items():
            try:
                if isinstance(job, dict):
                    SyncJobConfig(**job)
                elif not isinstance(job, SyncJobConfig):
                    raise ValueError(f"Invalid type for sync job '{
                                     key}': expected dict or SyncJobConfig")
            except ValueError as e:
                for error in e.errors():
                    field = error['loc'][0]
                    msg = error['msg']
                    errors.append(f"Invalid configuration for sync job '{
                                  key}': {field} - {msg}")

            # Check for invalid fields
            if isinstance(job, dict):
                invalid_fields = set(job.keys()) - \
                    set(SyncJobConfig.model_fields.keys())
                if invalid_fields:
                    errors.append(f"Sync job '{key}' contains invalid fields: {
                                  ', '.join(invalid_fields)}")

        return errors

    def get_status_file_path(self, job_key):
        local_path = self._config.sync_jobs[job_key].local
        remote_path = f"{self._config.sync_jobs[job_key].rclone_remote}:{
            self._config.sync_jobs[job_key].remote}"
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

    def get_sync_jobs(self):
        return self._config.sync_jobs

    def set_dry_run(self, value):
        self._config.dry_run = value

    def set_force_resync(self, value):
        self._config.force_resync = value

    def set_force_operation(self, value):
        self._config.force_operation = value

    def get_exclusion_rules_file(self):
        return self._config.exclusion_rules_file

    def get_max_cpu_usage_percent(self):
        return self._config.max_cpu_usage_percent

    def get_run_missed_jobs(self):
        return self._config.run_missed_jobs

    def get_run_initial_sync_on_startup(self):
        return self._config.run_initial_sync_on_startup

    def get_dry_run(self):
        return self._config.dry_run

    def get_force_resync(self):
        return self._config.force_resync

    def set_max_cpu_usage_percent(self, value):
        self._config.max_cpu_usage_percent = value

    def get_hash_warnings(self):
        return self._config.hash_warnings

    def get_last_sync_times(self):
        return self._config.last_sync_times

    def get_log_file_path(self):
        return self.log_file_path


config = Config()


def signal_handler(signum, frame):
    config.running = False
    config.shutting_down = True
    from logging_utils import log_message
    log_message('SIGINT or SIGTERM received. Initiating graceful shutdown.')
    print('SIGINT or SIGTERM received. Initiating graceful shutdown.')
    if hasattr(config, 'lock_fd'):
        config.lock_fd.close()
