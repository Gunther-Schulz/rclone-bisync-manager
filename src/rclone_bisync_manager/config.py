import yaml
import os
from datetime import datetime
import hashlib
from croniter import croniter
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, DirectoryPath
from rclone_bisync_manager.logging_utils import log_message, log_error


class OptionsValidatorMixin(BaseModel):
    rclone_options: Dict[str, Any] = Field(default_factory=dict)
    bisync_options: Dict[str, Any] = Field(default_factory=dict)
    resync_options: Dict[str, Any] = Field(default_factory=dict)

    @field_validator('rclone_options', 'bisync_options', 'resync_options')
    @classmethod
    def validate_options(cls, v, info):
        disallowed_keys = {'resync', 'bisync', 'log-file'}

        invalid_keys = set(v.keys()) & disallowed_keys
        if invalid_keys:
            field_name = getattr(info, 'field_name', 'options')
            raise ValueError(
                f"The following keys are not allowed in {field_name}: {', '.join(invalid_keys)}"
            )
        return v


class SyncJobConfig(OptionsValidatorMixin):
    local: str
    rclone_remote: str
    remote: str
    schedule: str
    active: bool = Field(default=True)
    dry_run: bool = Field(default=False)
    force_resync: bool = Field(default=False)
    force_operation: bool = Field(default=False)

    @field_validator('schedule')
    @classmethod
    def validate_cron(cls, v):
        try:
            croniter(v)
        except ValueError as e:
            raise ValueError(f"Invalid cron string: {str(e)}")
        return v


class ConfigSchema(OptionsValidatorMixin):
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

    @field_validator('sync_jobs', mode='before')
    @classmethod
    def validate_sync_jobs(cls, v):
        if v is None:
            raise ValueError(
                "sync_jobs cannot be None. Please provide at least one sync job.")
        if not isinstance(v, dict):
            raise ValueError(
                "sync_jobs must be a mapping (dict) of job keys to job configs.")

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
                    loc = error.get('loc', []) if isinstance(error, dict) else []
                    msg = error.get('msg', str(error)) if isinstance(error, dict) else str(error)
                    field = '.'.join(str(x) for x in loc) if loc else '?'
                    errors.append(f"Validation error for sync job '{key}': {field} - {msg}")

        if errors:
            raise ValueError("\n".join(errors))

        if not validated_jobs:
            raise ValueError(
                "No valid sync jobs found. Please provide at least one valid sync job.")

        return validated_jobs


class LogStatePersistence:
    """Holds mutable log state (last_log_position, hash_warnings). Config owns one and exposes via properties."""
    __slots__ = ('last_log_position', 'hash_warnings')

    def __init__(self):
        self.last_log_position = 0
        self.hash_warnings = {}


class Config:
    def __init__(self):
        self.default_config_file = os.path.join(os.environ.get(
            'XDG_CONFIG_HOME', os.path.expanduser('~/.config')), 'rclone-bisync-manager', 'config.yaml')
        self.config_file = self.default_config_file
        self._config = None
        self.args = None
        self._init_file_paths()
        self._init_logging_paths()
        self.console_log = False
        self.specific_sync_jobs = None
        self.force_operation = False
        self.daemon_mode = False
        self.status_file_path = {}
        self._log_state = LogStatePersistence()
        self.last_config_status = None
        self.config_changed_on_disk = False
        self.last_config_mtime = None

    @property
    def _last_log_position(self):
        return self._log_state.last_log_position

    @_last_log_position.setter
    def _last_log_position(self, value):
        self._log_state.last_log_position = value

    @property
    def hash_warnings(self):
        return self._log_state.hash_warnings

    def _init_file_paths(self):
        self.cache_dir = os.path.join(os.environ.get(
            'XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'rclone-bisync-manager')
        self.rclone_test_file_name = "RCLONE_TEST"

    def _init_logging_paths(self):
        self.default_log_dir = os.path.join(os.environ.get(
            'XDG_STATE_HOME', os.path.expanduser('~/.local/state')), 'rclone-bisync-manager', 'logs')
        self.log_file_path = os.path.join(
            self.default_log_dir, 'rclone-bisync-manager.log')

    def set_config_file(self, config_file):
        self.config_file = os.path.expanduser(config_file)
        self._init_file_paths()
        self._init_logging_paths()

    def initialize_config(self, args):
        self.args = args
        if hasattr(args, 'config') and args.config:
            self.set_config_file(args.config)
        self._update_internal_fields(args)

    def load_and_validate_config(self, args):
        self.args = args
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_file}")

        try:
            with open(self.config_file, 'r', encoding='utf-8', errors='replace') as f:
                config_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            error_message = f"Error parsing YAML in configuration file: {
                str(e)}"
            log_error(error_message)
            raise ValueError(error_message)

        # Merge CLI arguments into config_data
        self._merge_cli_args(config_data, args)

        try:
            new_config = ConfigSchema(**config_data)

            if self._config != new_config:
                self._config = new_config
                log_message("Configuration loaded and validated successfully.")
        except ValidationError as e:
            error_message = self._format_validation_errors(e)
            log_error(f"Configuration on disk is invalid: {error_message}")
            raise ValueError(error_message)

        self._populate_status_file_paths()
        self._update_internal_fields(args)

    def _merge_cli_args(self, config_data, args):
        # Override global options
        config_data['dry_run'] = getattr(args, 'dry_run', False)

        config_data.setdefault('sync_jobs', {})
        sync_jobs = config_data['sync_jobs']
        # Override sync job options
        if hasattr(args, 'specific_sync_jobs') and args.specific_sync_jobs:
            for job_key in args.specific_sync_jobs:
                if job_key in sync_jobs:
                    sync_jobs[job_key]['active'] = True

        resync_list = getattr(args, 'resync', None) or []
        if resync_list:
            for job_key in resync_list:
                if job_key in sync_jobs:
                    sync_jobs[job_key]['force_resync'] = True

        force_bisync_or_op = getattr(args, 'force_operation', False) or getattr(args, 'force_bisync', False)
        if force_bisync_or_op:
            for job_key in sync_jobs:
                sync_jobs[job_key]['force_operation'] = True

    def _update_internal_fields(self, args):
        self.console_log = getattr(args, 'console_log', False)
        self.specific_sync_jobs = args.sync_jobs if hasattr(
            args, 'sync_jobs') else None
        self.force_operation = args.force_bisync if hasattr(
            args, 'force_bisync') else False
        self.daemon_mode = getattr(args, 'command', None) == 'daemon'

    def _format_validation_errors(self, e):
        error_messages = []
        for error in e.errors():
            if isinstance(error, dict):
                loc = error.get('loc', [])
                msg = error.get('msg', str(error))
                field = '.'.join(str(x) for x in loc) if loc else '?'
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

    def check_config_changed(self):
        try:
            current_mtime = os.path.getmtime(self.config_file)
        except OSError:
            return
        if self.last_config_mtime is None:
            self.last_config_mtime = current_mtime
        elif current_mtime > self.last_config_mtime:
            self.config_changed_on_disk = True
            self.last_config_mtime = current_mtime

    def reset_config_changed_flag(self):
        self.config_changed_on_disk = False
        try:
            self.last_config_mtime = os.path.getmtime(self.config_file)
        except OSError:
            self.last_config_mtime = None


config = Config()


def signal_handler(signum, frame):
    from rclone_bisync_manager.daemon_state import daemon_state
    if daemon_state is not None:
        daemon_state.running = False
        daemon_state.shutting_down = True
        log_message('SIGINT or SIGTERM received. Initiating graceful shutdown.')
        if getattr(daemon_state, 'lock_fd', None) is not None:
            try:
                import fcntl
                fcntl.lockf(daemon_state.lock_fd, fcntl.LOCK_UN)
                os.close(daemon_state.lock_fd)
            except (OSError, IOError):
                pass
            daemon_state.lock_fd = None


def get_config_schema():
    """Return JSON schema for config models (Pydantic v2)."""
    return {
        "ConfigSchema": ConfigSchema.model_json_schema(),
        "SyncJobConfig": SyncJobConfig.model_json_schema(),
        "OptionsValidatorMixin": OptionsValidatorMixin.model_json_schema(),
    }
