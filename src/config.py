import yaml
import os
from datetime import datetime
from threading import Lock
from queue import Queue
import hashlib
from croniter import croniter
import json
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, ValidationError, field_validator


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
    status_file_path: Dict[str, str] = {}
    log_file_path: str = Field(default_factory=lambda: os.path.join(
        os.environ.get('XDG_STATE_HOME', os.path.expanduser('~/.local/state')),
        'rclone-bisync-manager',
        'logs',
        'rclone-bisync-manager.log'
    ))
    hash_warnings: Dict[str, Optional[str]] = {}
    sync_errors: Dict[str, str] = {}

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

    def load_and_validate_config(self, args):
        self.args = args
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_file}")

        with open(self.config_file, 'r') as f:
            config_data = yaml.safe_load(f)

        self._validate_global_keys(config_data)
        self._validate_sync_job_keys(config_data)
        self._update_config_with_args(config_data, args)

        try:
            self._config = ConfigSchema(**config_data)
            self._validate_config_schema()
        except ValidationError as e:
            raise ValueError(self._format_validation_errors(e))

        self._populate_status_file_paths()

    def _validate_global_keys(self, config_data):
        allowed_keys = self._get_global_allowed_keys(
        ) | self._get_shared_allowed_keys() | {'sync_jobs'}
        unrecognized_keys = set(config_data.keys()) - allowed_keys
        if unrecognized_keys:
            raise ValueError(f"Unrecognized global options: {
                             ', '.join(unrecognized_keys)}")

    def _validate_sync_job_keys(self, config_data):
        if 'sync_jobs' in config_data:
            allowed_keys = set(SyncJobConfig.model_fields.keys())
            for job_key, job_config in config_data['sync_jobs'].items():
                unrecognized_keys = set(job_config.keys()) - allowed_keys
                if unrecognized_keys:
                    raise ValueError(f"Unrecognized keys in sync job '{
                                     job_key}': {', '.join(unrecognized_keys)}")

    def _update_config_with_args(self, config_data, args):
        config_data.update({
            'dry_run': args.dry_run,
            'force_resync': args.force_resync,
            'console_log': args.console_log,
            'specific_sync_jobs': args.specific_sync_jobs,
            'force_operation': args.force_operation,
            'daemon_mode': args.daemon_mode
        })

    def _validate_config_schema(self):
        errors = []
        errors.extend(self._validate_global_options())
        errors.extend(self._validate_sync_jobs())
        if errors:
            raise ValidationError(errors)

    def _format_validation_errors(self, e):
        error_messages = []
        for error in e.errors():
            field = '.'.join(error['loc'])
            msg = error['msg']
            error_messages.append(f"Error in {field}: {msg}")
        return "\n".join(error_messages)

    def _populate_status_file_paths(self):
        for job_key in self._config.sync_jobs.keys():
            self._config.status_file_path[job_key] = self.get_status_file_path(
                job_key)

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
                    errors.append(f"Invalid type for sync job '{
                                  key}': expected dict or SyncJobConfig")
            except ValidationError as e:
                for error in e.errors():
                    field = error['loc'][0]
                    msg = error['msg']
                    errors.append(f"Invalid configuration for sync job '{
                                  key}': {field} - {msg}")
        return errors

    def get_status_file_path(self, job_key):
        if job_key in self._config.status_file_path:
            return self._config.status_file_path[job_key]
        else:
            # Calculate the path if it's not in the dictionary (this shouldn't happen in normal operation)
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


config = Config()


def signal_handler(signum, frame):
    config.running = False
    config.shutting_down = True
    from logging_utils import log_message
    log_message('SIGINT or SIGTERM received. Initiating graceful shutdown.')
    print('SIGINT or SIGTERM received. Initiating graceful shutdown.')
    if hasattr(config, 'lock_fd'):
        config.lock_fd.close()
