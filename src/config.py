import yaml
import os
from datetime import datetime
from threading import Lock
from queue import Queue
import hashlib
from croniter import croniter
import json
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, constr, conint, DirectoryPath

debug = False


class SyncJobConfig(BaseModel):
    local: str
    rclone_remote: str
    remote: str
    schedule: str
    active: bool = Field(default=True)
    dry_run: bool = Field(default=False)
    force_resync: bool = Field(default=False)
    force_operation: bool = Field(default=False)
    rclone_options: Dict[str, Any] = Field(default_factory=dict)
    bisync_options: Dict[str, Any] = Field(default_factory=dict)
    resync_options: Dict[str, Any] = Field(default_factory=dict)

    @field_validator('schedule')
    @classmethod
    def validate_cron(cls, v):
        try:
            croniter(v)
        except ValueError as e:
            raise ValueError(f"Invalid cron string: {str(e)}")
        return v


class SyncState:
    def __init__(self):
        self.sync_status = {}
        self.resync_status = {}
        self.last_sync_times = {}
        self.next_run_times = {}

    def update_job_state(self, job_key, sync_status=None, resync_status=None, last_sync=None, next_run=None):
        if sync_status is not None:
            self.sync_status[job_key] = sync_status
        if resync_status is not None:
            self.resync_status[job_key] = resync_status
        if last_sync is not None:
            self.last_sync_times[job_key] = last_sync
        if next_run is not None:
            self.next_run_times[job_key] = next_run

    def get_job_state(self, job_key):
        return {
            "sync_status": self.sync_status.get(job_key, "NONE"),
            "resync_status": self.resync_status.get(job_key, "NONE"),
            "last_sync": self.last_sync_times.get(job_key),
            "next_run": self.next_run_times.get(job_key)
        }


sync_state = SyncState()


class ConfigSchema(BaseModel):
    # Base path for local files to be synced
    local_base_path: DirectoryPath

    # Path to exclusion rules file (optional)
    exclusion_rules_file: Optional[str] = None

    # CPU usage limit as a percentage
    max_cpu_usage_percent: int = Field(default=100, ge=0, le=100)

    # Whether to redirect rclone log output
    redirect_rclone_log_output: bool = False

    # Whether to run missed jobs
    run_missed_jobs: bool = False

    # Whether to run initial sync on startup
    run_initial_sync_on_startup: bool = True

    # Global rclone options
    rclone_options: Dict[str, Any] = Field(default_factory=dict)

    # Global bisync options
    bisync_options: Dict[str, Any] = Field(default_factory=dict)

    # Global resync options
    resync_options: Dict[str, Any] = Field(default_factory=dict)

    # Sync job configurations
    sync_jobs: Dict[str, SyncJobConfig]

    # Whether to run in dry-run mode
    dry_run: bool = False

    # Path to log file
    log_file_path: str = Field(default_factory=lambda: os.path.join(
        os.environ.get('XDG_STATE_HOME', os.path.expanduser('~/.local/state')),
        'rclone-bisync-manager',
        'logs',
        'rclone-bisync-manager.log'
    ))

    model_config = ConfigDict(extra='forbid')

    @field_validator('max_cpu_usage_percent')
    @classmethod
    def check_cpu_usage(cls, v):
        if v < 0 or v > 100:
            raise ValueError('max_cpu_usage_percent must be between 0 and 100')
        return v

    @field_validator('sync_jobs', mode='before')
    @classmethod
    def validate_sync_jobs(cls, v):
        if debug:
            print("Entering validate_sync_jobs method")
            print(f"Input value: {v}")

        validated_jobs = {}
        errors = []

        for key, job in v.items():
            if not isinstance(key, str):
                errors.append(f"Invalid job key: {
                              key}. Job keys must be strings.")
                continue

            try:
                # Check for required keys
                required_keys = {
                    'local', 'rclone_remote', 'remote', 'schedule'}
                missing_keys = required_keys - set(job.keys())
                if missing_keys:
                    errors.append(f"Missing required keys in sync job '{
                                  key}': {', '.join(missing_keys)}")

                # Check for invalid keys
                allowed_keys = set(SyncJobConfig.model_fields.keys())
                invalid_keys = set(job.keys()) - allowed_keys
                if invalid_keys:
                    errors.append(f"Invalid keys found in sync job '{
                                  key}': {', '.join(invalid_keys)}")

                if not missing_keys and not invalid_keys:
                    validated_jobs[key] = SyncJobConfig(**job)
            except ValidationError as e:
                for error in e.errors():
                    field = '.'.join(str(loc) for loc in error['loc'])
                    msg = error['msg']
                    errors.append(f"Validation error for sync job '{
                                  key}': {field} - {msg}")

        if errors:
            raise ValueError("\n".join(errors))

        if debug:
            print("Exiting validate_sync_jobs method")
            print(f"Validated jobs: {validated_jobs}")
        return validated_jobs


class Config:
    def __init__(self):
        self._config = None
        self.args = None
        self.config_file = None
        self.config_invalid = False
        self.config_error_message = None
        self.LOCK_FILE_PATH = '/tmp/rclone_bisync_manager.lock'
        self._init_file_paths()
        self._init_logging_paths()
        self.load_sync_state()
        self.sync_queue = Queue()
        self.queued_paths = set()
        self.sync_lock = Lock()
        self.currently_syncing = None
        self.current_sync_start_time = None
        self.running = True
        self.shutting_down = False
        self.shutdown_complete = False
        self.console_log = False
        self.specific_sync_jobs = None
        self.force_operation = False
        self.daemon_mode = False
        self.status_file_path = {}
        self.hash_warnings = {}
        self.sync_errors = {}

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
        if debug:
            print("Entering load_and_validate_config method")
        self.args = args
        if not os.path.exists(self.config_file):
            if debug:
                print(f"Error: Configuration file not found: {
                      self.config_file}")
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_file}")

        with open(self.config_file, 'r') as f:
            config_data = yaml.safe_load(f)

        if debug:
            print("Config data loaded from file:")
            print(json.dumps(config_data, indent=2))

        self._update_config_with_args(config_data, args)

        if debug:
            print("Config data after updating with args:")
            print(json.dumps(config_data, indent=2))

        try:
            if debug:
                print("Attempting to create ConfigSchema")
            self._config = ConfigSchema(**config_data)
            if debug:
                print("ConfigSchema created successfully")
                print("Sync jobs after validation:")
                print(json.dumps({k: v.model_dump()
                      for k, v in self._config.sync_jobs.items()}, indent=2))
            self.config_invalid = False
            self.config_error_message = None
        except ValidationError as e:
            if debug:
                print(f"ValidationError caught: {e}")
            error_message = self._format_validation_errors(e)
            if debug:
                print(f"Formatted error message:\n{error_message}")
            self.config_invalid = True
            self.config_error_message = error_message
            raise ValueError(error_message)

        self._populate_status_file_paths()
        self._update_internal_fields(args)
        if debug:
            print("Exiting load_and_validate_config method")

    def _update_config_with_args(self, config_data, args):
        config_data.update({
            'dry_run': args.dry_run,
        })

    def _update_internal_fields(self, args):
        self.console_log = args.console_log
        self.specific_sync_jobs = args.specific_sync_jobs
        self.force_operation = args.force_operation
        self.daemon_mode = args.daemon_mode

    def _format_validation_errors(self, e):
        error_messages = []
        for error in e.errors():
            if isinstance(error, dict):
                field = '.'.join(str(loc) for loc in error['loc'])
                msg = error['msg']
                error_messages.append(f"Error in {field}: {msg}")
            else:
                error_messages.append(str(error))
        return "\n".join(error_messages)

    def _populate_status_file_paths(self):
        for job_key in self._config.sync_jobs.keys():
            self.status_file_path[job_key] = self.get_status_file_path(job_key)

    def get_status_file_path(self, job_key):
        if job_key in self.status_file_path:
            return self.status_file_path[job_key]
        else:
            local_path = self._config.sync_jobs[job_key].local
            remote_path = f"{self._config.sync_jobs[job_key].rclone_remote}:{
                self._config.sync_jobs[job_key].remote}"
            unique_id = hashlib.md5(f"{job_key}:{local_path}:{
                                    remote_path}".encode()).hexdigest()
            return os.path.join(self.cache_dir, f'{unique_id}.status')

    def save_sync_state(self):
        state_file = os.path.join(self.cache_dir, 'sync_state.json')
        with open(state_file, 'w') as f:
            json.dump({
                "sync_status": sync_state.sync_status,
                "resync_status": sync_state.resync_status,
                "last_sync_times": {k: v.isoformat() for k, v in sync_state.last_sync_times.items()},
                "next_run_times": {k: v.isoformat() for k, v in sync_state.next_run_times.items()}
            }, f)

    def load_sync_state(self):
        state_file = os.path.join(self.cache_dir, 'sync_state.json')
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                state = json.load(f)
                sync_state.sync_status = state.get("sync_status", {})
                sync_state.resync_status = state.get("resync_status", {})
                sync_state.last_sync_times = {k: datetime.fromisoformat(
                    v) for k, v in state.get("last_sync_times", {}).items()}
                sync_state.next_run_times = {k: datetime.fromisoformat(
                    v) for k, v in state.get("next_run_times", {}).items()}
        else:
            sync_state.sync_status = {}
            sync_state.resync_status = {}
            sync_state.last_sync_times = {}
            sync_state.next_run_times = {}


config = Config()


def signal_handler(signum, frame):
    if config._config is not None:
        config.running = False
        config.shutting_down = True
        from logging_utils import log_message
        log_message('SIGINT or SIGTERM received. Initiating graceful shutdown.')
        if hasattr(config, 'lock_fd'):
            config.lock_fd.close()
