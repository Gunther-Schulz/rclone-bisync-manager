"""Sync state and sync_errors persistence. Separate from Config (loaded YAML, paths)."""

import json
import os
from datetime import datetime

from rclone_bisync_manager.logging_utils import log_error, log_message


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


class SyncStateStore:
    """Holds sync_state and sync_errors; loads/saves to cache_dir."""

    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        self.sync_state = SyncState()
        self.sync_errors = {}
        self._sync_errors_file = os.path.join(cache_dir, 'sync_errors.json')

    def load(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        state_file = os.path.join(self.cache_dir, 'sync_state.json')
        if os.path.exists(state_file) and os.path.getsize(state_file) > 0:
            try:
                with open(state_file, 'r', encoding='utf-8', errors='replace') as f:
                    state = json.load(f)
                    self.sync_state.sync_status = state.get("sync_status", {})
                    self.sync_state.resync_status = state.get("resync_status", {})
                    def parse_dt(mapping):
                        out = {}
                        for k, v in (mapping or {}).items():
                            try:
                                out[k] = datetime.fromisoformat(v) if isinstance(v, str) else v
                            except (ValueError, TypeError):
                                pass
                        return out
                    self.sync_state.last_sync_times = parse_dt(state.get("last_sync_times"))
                    self.sync_state.next_run_times = parse_dt(state.get("next_run_times"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                log_error("Error decoding sync_state.json. Initializing with empty state.")
                self._initialize_empty_sync_state()
        else:
            log_message("sync_state.json is empty or doesn't exist. Initializing with empty state.")
            self._initialize_empty_sync_state()
        self._load_sync_errors()

    def _serialize_datetime_dict(self, d):
        """Serialize dict of datetime values; skip non-datetime or None to avoid AttributeError."""
        out = {}
        for k, v in (d or {}).items():
            if v is not None and hasattr(v, 'isoformat'):
                out[k] = v.isoformat()
        return out

    def save(self):
        """Save sync state atomically (write to temp file then rename)."""
        os.makedirs(self.cache_dir, exist_ok=True)
        state_file = os.path.join(self.cache_dir, 'sync_state.json')
        tmp_file = state_file + '.tmp'
        try:
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "sync_status": self.sync_state.sync_status,
                    "resync_status": self.sync_state.resync_status,
                    "last_sync_times": self._serialize_datetime_dict(self.sync_state.last_sync_times),
                    "next_run_times": self._serialize_datetime_dict(self.sync_state.next_run_times)
                }, f)
            os.replace(tmp_file, state_file)
        except OSError:
            if os.path.exists(tmp_file):
                try:
                    os.unlink(tmp_file)
                except OSError:
                    pass
            raise
        self._save_sync_errors()

    def _initialize_empty_sync_state(self):
        self.sync_state.sync_status = {}
        self.sync_state.resync_status = {}
        self.sync_state.last_sync_times = {}
        self.sync_state.next_run_times = {}

    def _save_sync_errors(self):
        """Save sync_errors atomically (write to temp file then rename)."""
        tmp_file = self._sync_errors_file + '.tmp'
        try:
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(self.sync_errors, f, default=str)
            os.replace(tmp_file, self._sync_errors_file)
        except OSError:
            if os.path.exists(tmp_file):
                try:
                    os.unlink(tmp_file)
                except OSError:
                    pass
            raise

    def _load_sync_errors(self):
        if os.path.exists(self._sync_errors_file):
            try:
                with open(self._sync_errors_file, 'r', encoding='utf-8', errors='replace') as f:
                    self.sync_errors = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                log_error("Error decoding sync_errors.json. Starting with empty sync_errors.")
                self.sync_errors = {}
        else:
            self.sync_errors = {}

    def update_sync_error(self, local_path, sync_type, error_code, message):
        self.sync_errors[local_path] = {
            "sync_type": sync_type,
            "error_code": error_code,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        self._save_sync_errors()

    def remove_sync_error(self, local_path):
        if local_path in self.sync_errors:
            del self.sync_errors[local_path]
            self._save_sync_errors()


# Mutable ref so get_sync_state_store can assign without global keyword
_store_ref = [None]


def get_sync_state_store():
    """Return the singleton SyncStateStore, creating and loading it on first use."""
    if _store_ref[0] is None:
        from rclone_bisync_manager.config import get_config
        _store_ref[0] = SyncStateStore(get_config().cache_dir)
        _store_ref[0].load()
    return _store_ref[0]
