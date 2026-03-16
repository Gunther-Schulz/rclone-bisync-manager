#!/usr/bin/env python3

from PIL import Image
import json
import time
import subprocess
import os
import tempfile
from io import BytesIO
from cairosvg import svg2png
import argparse
import logging
import traceback
from queue import Queue
from threading import Thread, Lock
from rclone_bisync_manager.runtime_paths import clear_crash_log, read_crash_log
from rclone_bisync_manager.logging_utils import log_message, set_config, setup_loggers
from rclone_bisync_manager.daemon_client import (
    request_status,
    request_stop,
    request_reload,
    request_add_sync,
)
from rclone_bisync_manager.config import get_default_config_file
from rclone_bisync_manager import status_protocol as sp
from rclone_bisync_manager.status_protocol import DaemonState, status_to_display_state, _has_sync_issues
import sys

# AppIndicator3 (SNI) + GTK only; required for tray
APPINDICATOR_AVAILABLE = False
NOTIFY_AVAILABLE = False
try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import Gtk, GLib, AppIndicator3
    APPINDICATOR_AVAILABLE = True
    try:
        gi.require_version("Notify", "0.7")
        from gi.repository import Notify
        NOTIFY_AVAILABLE = True
    except (ImportError, ValueError):
        Notify = None
except (ImportError, ValueError):
    Gtk = GLib = AppIndicator3 = Notify = None

# App/indicator identity (used for Notify, AppIndicator, tray icon filenames, package version)
_APP_ID = "rclone-bisync-manager"
_TRAY_ICON_PREFIX = f"{_APP_ID}-tray-icon-"

# CLI subcommands and args (start_daemon, argparse)
_CMD_DAEMON = "daemon"
_CMD_START = "start"
_ARG_CONFIG = "--config"

# Subprocess: open directory (non-Windows)
_CMD_XDG_OPEN = "xdg-open"

# Tray icon file format, extension, and AppIndicator description
_ICON_FORMAT = "PNG"
_ICON_EXT = ".png"
_ICON_DESC_STATUS = "{} status"

# Tray state: single mutable ref (no global keyword); see get_tray_state/set_tray_state
_tray_state_ref = [None]


class TrayState:
    """Mutable holder for tray runtime state. Set once in run_tray_appindicator."""

    def __init__(self):
        self.daemon_manager = None
        self.args = None
        self.update_queue = None
        self.last_status = None
        self.last_status_lock = None
        self.offline_miss_count = 0
        self.indicator = None
        self.icon_paths = None
        self.icon_counter = 0  # unique path per update so AppIndicator always reloads (no cache)
        self.status_window_gtk = None


def get_tray_state():
    """Return current tray state or None if not set."""
    return _tray_state_ref[0]


def _get_tray_state_and_daemon():
    """Return (state, daemon_manager) or (None, None) if state invalid or no daemon_manager."""
    state = get_tray_state()
    if state is None or state.daemon_manager is None:
        return None, None
    return state, state.daemon_manager


def set_tray_state(state):
    """Set current tray state (called from run_tray_appindicator)."""
    _tray_state_ref[0] = state


# Minimum time (seconds) to show syncing icon so quick syncs still give visible feedback
MIN_SYNC_FEEDBACK_SECONDS = 2.0

# Consecutive None polls after which we clear last_status so UI shows OFFLINE (single source of truth)
OFFLINE_CLEAR_AFTER_MISSES = 5

# Poll loop sleep (seconds) in check_status_and_update
_POLL_LOOP_SLEEP_SECONDS = 1

# request_status() defaults used by get_daemon_status, _status_fetch_worker
_REQUEST_STATUS_TIMEOUT = 8
_REQUEST_STATUS_RETRIES = 2
_REQUEST_STATUS_RETRY_DELAY = 0.3

# stop_daemon: request_stop and post-stop poll
_STOP_REQUEST_TIMEOUT = 5
_STOP_REQUEST_RETRIES = 2
_STOP_REQUEST_RETRY_DELAY = 0.3
_STOP_POLL_ATTEMPTS = 6
_STOP_POLL_INTERVAL = 2
_STOP_POLL_TIMEOUT = 2

# start_daemon: subprocess wait
_DAEMON_START_WAIT_TIMEOUT = 2

# Ensures at most one status fetch runs at a time; fetch runs in a worker so poll loop never blocks on socket
_status_fetch_in_progress = [False]
_status_fetch_lock = Lock()


class Colors:
    YELLOW = (255, 235, 59)
    GREEN = (76, 175, 80)
    BLUE = (33, 150, 243)
    GRAY = (158, 158, 158)
    PURPLE = (156, 39, 176)
    RED = (244, 67, 54)
    AMBER = (255, 193, 7)


_STATE_COLORS = {
    DaemonState.INITIAL: Colors.YELLOW,
    DaemonState.STARTING: Colors.YELLOW,
    DaemonState.RUNNING: Colors.GREEN,
    DaemonState.SYNCING: Colors.BLUE,
    DaemonState.SHUTTING_DOWN: Colors.PURPLE,
    DaemonState.SYNC_ISSUES: Colors.RED,
    DaemonState.CONFIG_INVALID: Colors.RED,
    DaemonState.CONFIG_CHANGED: Colors.AMBER,
    DaemonState.LIMBO: Colors.PURPLE,
    DaemonState.OFFLINE: Colors.GRAY,
    DaemonState.FAILED: Colors.RED,
}

# Short display names for state (status window title, menu, etc.)
_DISPLAY_RUNNING = "Running"
_DISPLAY_SYNCING = "Syncing"
_DISPLAY_LIMBO = "Limbo"
_DISPLAY_INITIAL = "Initializing"
_DISPLAY_CONFIG_CHANGED = "Config changed"
_DISPLAY_CONFIG_INVALID = "Config invalid"
_DISPLAY_SYNC_ISSUES = "Sync issues"
_DISPLAY_SHUTTING_DOWN = "Shutting down"
_DISPLAY_OFFLINE = "Offline"
_DISPLAY_FAILED = "Not running"

_STATE_DISPLAY_NAMES = {
    DaemonState.RUNNING: _DISPLAY_RUNNING,
    DaemonState.SYNCING: _DISPLAY_SYNCING,
    DaemonState.LIMBO: _DISPLAY_LIMBO,
    DaemonState.INITIAL: _DISPLAY_INITIAL,
    DaemonState.CONFIG_CHANGED: _DISPLAY_CONFIG_CHANGED,
    DaemonState.CONFIG_INVALID: _DISPLAY_CONFIG_INVALID,
    DaemonState.SYNC_ISSUES: _DISPLAY_SYNC_ISSUES,
    DaemonState.SHUTTING_DOWN: _DISPLAY_SHUTTING_DOWN,
    DaemonState.OFFLINE: _DISPLAY_OFFLINE,
    DaemonState.FAILED: _DISPLAY_FAILED,
}

# States for which Edit Config and Reload Config are enabled/disabled in the menu
_EDIT_CONFIG_STATES = (DaemonState.RUNNING, DaemonState.SYNCING, DaemonState.CONFIG_INVALID, DaemonState.CONFIG_CHANGED, DaemonState.LIMBO, DaemonState.SYNC_ISSUES)
_RELOAD_DISABLED_STATES = (DaemonState.INITIAL, DaemonState.SHUTTING_DOWN)

# States that mean daemon is not running (for status window offline/error UI)
_STATES_NO_DAEMON = (DaemonState.OFFLINE, DaemonState.FAILED)

# Menu/status label for shutting-down state (used in menu and status window)
_LABEL_SHUTTING_DOWN = "Daemon is shutting down..."

# stop_daemon notification (title and body)
_NOTIFY_STOP_TITLE = "Daemon is shutting down"
_NOTIFY_STOP_BODY = "The daemon will stop shortly."
_NOTIFY_STOP_FAIL_TITLE = "Stop failed"

# _require_path / open_config_file / open_log_folder / edit_config
_MSG_PATH_UNAVAILABLE = "Path not available. Is the daemon running?"
_NOTIFY_CONFIG_FOLDER_TITLE = "Config folder"
_LOG_MSG_CONFIG_PATH_NOT_FOUND = "Config file path not found"
_LOG_MSG_LOG_PATH_NOT_FOUND = "Log file path not found"
_MSG_CONFIG_PATH_UNAVAILABLE = "Config file path not available"

# Default window sizes (width, height)
_STATUS_WINDOW_SIZE = (500, 380)
_TEXT_WINDOW_SIZE = (600, 400)

# start_daemon / reload notifications
_NOTIFY_ALREADY_RUNNING_TITLE = "Daemon already running"
_NOTIFY_ALREADY_RUNNING_BODY = "The daemon is already running."
_NOTIFY_START_FAIL_TITLE = "Daemon failed to start"
_NOTIFY_RELOAD_FAIL_TITLE = "Config reload failed"
_NOTIFY_RELOAD_SUCCESS_TITLE = "Config reloaded"
_NOTIFY_RELOAD_SUCCESS_BODY = "Configuration was reloaded successfully."
_NOTIFY_SYNC_QUEUED_TITLE = "Sync queued"
_NOTIFY_SYNC_ERROR_TITLE = "Sync Error"

# Default icon stroke thickness (SVG and create_status_image)
_DEFAULT_ICON_THICKNESS = 40

# Fallback error strings (used in menu, status, reload, stop)
_UNKNOWN_ERROR = "Unknown error"
_UNKNOWN_ERROR_OCCURRED = "Unknown error occurred"
_TITLE_DAEMON_ERROR_LOG = "Daemon Error Log"
_MSG_CONFIG_NOT_FOUND = "Config file not found or inaccessible."
_MSG_LOG_NO_DIR = "Log path has no directory component."
_MSG_STOP_MAY_STILL_RUNNING = "Daemon may still be running."
_NOTIFY_LOG_FOLDER_TITLE = "Log folder"

# API response keys and values (stop_daemon, reload_config, add_to_sync_queue)
_STOP_RESPONSE_KEY_STATUS = "status"
_STOP_RESPONSE_KEY_MESSAGE = "message"
_STOP_RESULT_SUCCESS = "success"
_RELOAD_STATUS_SUCCESS = "success"
_SYNC_QUEUE_RESPONSE_OK = "OK"

# Default gray hex for icon when color is not a valid tuple (matches Colors.GRAY)
_HEX_GRAY = "#9e9e9e"

# Truncation limits for menu/error text and debug logs
_TRUNCATE_ERROR_LINE = 80
_TRUNCATE_MENU_ERROR = 30
_TRUNCATE_START_FAIL = 200
_TRUNCATE_DEBUG_STATUS = 100

# Menu and status window labels (reused across failed/offline/limbo/normal spec and status window)
_LABEL_DAEMON_NOT_RUNNING = "Daemon is not running"
_LABEL_DAEMON_NOT_RUNNING_WARN = "⚠️ Daemon is not running"
_LABEL_LIMBO_STATE = "⚠️ Daemon is in limbo state"
_LABEL_CONFIG_INVALID = "⚠️ Config is invalid"
_LABEL_CONFIG_CHANGED_DISK = "⚠️ Config changed on disk"
_LABEL_SHOW_FULL_ERROR = "Show Full Error"
_LABEL_CURRENTLY_SYNCING = "Currently syncing:"
_LABEL_QUEUED_JOBS = "Queued jobs:"
_LABEL_SYNC_JOBS = "Sync Jobs"
_LABEL_LAST_SYNC = "Last sync:"
_LABEL_NEXT_RUN = "Next run:"
_LABEL_SYNC_STATUS = "Sync status:"
_LABEL_RESYNC_STATUS = "Resync status:"
_LABEL_NEVER = "Never"
_LABEL_NOT_SCHEDULED = "Not scheduled"
_LABEL_NA = "N/A"
_LABEL_STATUS_WINDOW_TITLE = "RClone BiSync Manager – "
_LABEL_CLICK_REFRESH = "Click Refresh to load latest status."
_LABEL_STARTING_DAEMON = "Starting daemon… The tray icon will update when ready."
_LABEL_TAB_GENERAL = "General"
_LABEL_TAB_SYNC_JOBS = "Sync Jobs"
_LABEL_TAB_SYNC_ERRORS = "Sync Errors"
_LABEL_TAB_CONFIG = "Config"
_LABEL_NO_SYNC_JOBS = "No sync jobs configured."
_LABEL_NO_SYNC_ERRORS = "No sync errors at this time."
_LABEL_STATUS_FALLBACK = "Status"
_LABEL_DAEMON_RUNNING = "Daemon is running"

# Menu: initializing, config submenu, actions
_LABEL_INITIALIZING = "Initializing..."
_LABEL_CONFIG_AND_LOGS = "Config & Logs"
_LABEL_RELOAD_CONFIG = "Reload Config"
_LABEL_EDIT_CONFIG = "Edit Configuration (experimental)"
_LABEL_OPEN_CONFIG_FOLDER = "Open Config Folder"
_LABEL_OPEN_LOG_FOLDER = "Open Log Folder"
_LABEL_SHOW_STATUS_WINDOW = "Show Status Window"
_LABEL_START_DAEMON = "Start Daemon"
_LABEL_STOP_DAEMON = "Stop Daemon"
_LABEL_EXIT_TRAY = "Exit Tray"
_LABEL_SYNC_ISSUES_DETECTED = "⚠ Sync issues detected"
_LABEL_SYNC_NOW = "⚡ Sync Now"
_LABEL_FORCE_SYNC_NOW = "⚡ Force Sync Now"
_LABEL_RESYNC_SYNC_NOW = "⚡ Resync + Sync Now"
_LABEL_BUTTON_REFRESH = "Refresh"
_LABEL_ERROR_PREFIX = "Error:"

# Status API value for failed/error state
_STATUS_VALUE_ERROR = "error"

# Repeated log messages (used in multiple call sites)
_LOG_DAEMON_MANAGER_UNAVAILABLE = "Daemon manager not available"
_LOG_CLEARED_CRASH_LOG = "Cleared existing crash log"
_LOG_STATUS_CHANGED = "Daemon status changed"
_LOG_STATUS_SERIALIZE_FAIL = "New status: (unable to serialize for debug)"
_LOG_RELOAD_SUCCESS = "Configuration reloaded successfully"
_LOG_STARTED_SUCCESS = "Daemon started successfully"
_LOG_EXITING_TRAY = "Exiting tray application"

# reload_config failure messages (log and notify)
_RELOAD_ERR_DAEMON_NOT_RUNNING = "Error reloading configuration: daemon not running"
_RELOAD_NOTIFY_DAEMON_NOT_RUNNING = "Daemon is not running."
_RELOAD_ERR_UNEXPECTED_RESPONSE = "Unexpected reload response from daemon"
_RELOAD_NOTIFY_UNEXPECTED_RESPONSE = "Unexpected response from daemon."

# start_daemon error message prefixes
_START_ERR_PREFIX = "Error starting daemon:"
_START_ERR_UNEXPECTED_PREFIX = "Unexpected error starting daemon:"

# Sync queue notifications (body format with {job_key})
_NOTIFY_SYNC_QUEUED_BODY = "Job '{}' was added to the sync queue."
_NOTIFY_SYNC_ERROR_BODY = "Failed to add sync job '{}' to queue. Check the logs for more information."

# edit_config error
_MSG_EDIT_CONFIG_FAIL = "Failed to edit config: {}"

# Log: stop_daemon, start_daemon, crash, log path
_LOG_STOP_PROGRESS = "Daemon is shutting down. Use 'daemon status' to check progress."
_LOG_START_ALREADY_RESPONDING = "Daemon start completed; daemon is already responding."
_LOG_START_REQUESTED = "Daemon start requested."
_LOG_START_TRAY_WILL_SHOW = "Tray will show status when the daemon responds."
_LOG_START_ALREADY_RUNNING = "Daemon is already running"
_LOG_START_ATTEMPTING = "Attempting to start daemon"
_LOG_LOG_PATH_NO_DIR = "Log path has no directory (e.g. plain filename); cannot open folder."
_LOG_DAEMON_CRASHED = "Daemon crashed."
_LOG_CRASH_MESSAGE = "Crash message: {}"

# Log: error message formats (one {} placeholder for exception/detail)
_LOG_ERR_COMMUNICATING_DAEMON = "Error communicating with daemon: {}"
_LOG_ERR_APPLYING_STATUS = "Error applying status result: {}"
_LOG_ERR_FETCHING_STATUS = "Error fetching daemon status: {}"
_LOG_ERR_STOP_DAEMON = "Failed to stop daemon: {}"
_LOG_ERR_ADD_SYNC_QUEUE = "Error adding job to sync queue: {}"
_LOG_ERR_WRITING_ICON = "Error writing tray icon: {}"
_LOG_ERR_UPDATING_UI = "Error updating tray UI: {}"
_LOG_ERR_HANDLE_UPDATES = "Error in handle_updates: {}"
_LOG_ERR_CHECK_STATUS = "Error in check_status_and_update: {}"
_LOG_ERR_EDITING_CONFIG = "Error editing config: {}"

# Status window General tab: Config Valid/Invalid, Yes/No
_LABEL_VALID = "Valid"
_LABEL_INVALID = "Invalid"
_LABEL_YES = "Yes"
_LABEL_NO = "No"

# Status window General tab: first-line status text per state (see _STATUS_WINDOW_STATUS_TEXT)
_STATUS_WIN_LIMBO = "⚠ Daemon is in limbo state"
_STATUS_WIN_INITIAL = "Daemon is initializing..."
_STATUS_WIN_SYNCING = "Syncing"
_STATUS_WIN_CONFIG_CHANGED = "⚠ Config changed on disk (reload from tray menu)"
_STATUS_WIN_CONFIG_INVALID = "⚠ Config invalid"
_STATUS_WIN_SYNC_ISSUES = "⚠ Sync issues detected"

# start_daemon: short failure fallback
_LOG_EXIT_CODE = "Exit code {}"

# reload_config: generic failure (message from API)
_RELOAD_ERR_PREFIX = "Error reloading configuration: {}"

# get_current_state: unexpected status type
_MSG_UNEXPECTED_STATUS_TYPE = "Unexpected status type: {}"

# Log: notification fallback and error details
_LOG_NOTIFICATION_FAILED = "Notification failed: {}; {} - {}"
_LOG_NOTIFICATION = "Notification: {} - {}"
_LOG_ERR_DETAILS = "Error details: {}"

# GTK CSS class for error styling
_CSS_CLASS_ERROR = "error"

# Menu spec keys and values (used by _build_gtk_menu when reading spec dicts)
_SPEC_KEY_TYPE = "type"
_SPEC_KEY_LABEL = "label"
_SPEC_KEY_ENABLED = "enabled"
_SPEC_KEY_SUBMENU = "submenu"
_SPEC_KEY_CALLBACK = "callback"
_SPEC_VALUE_SEPARATOR = "separator"
_SPEC_VALUE_ITEM = "item"

# Status window: display when value is missing (e.g. currently_syncing, queued jobs)
_LABEL_NONE = "None"

# Status window General tab: label prefixes for key-value lines
_LABEL_VERSION_LINE = "Version:"
_LABEL_PID_LINE = "PID:"
_LABEL_CONFIG_LINE = "Config:"
_LABEL_CONFIG_CHANGED_DISK_LINE = "Config changed on disk:"
_LABEL_CONFIG_FILE_LINE = "Config file:"
_LABEL_LOG_FILE_LINE = "Log file:"

# Status window layout (margins, spacing, min heights)
_STATUS_BOX_SPACING = 12
_STATUS_FRAME_BOX_SPACING = 4
_STATUS_BOX_MARGIN = 20
_STATUS_ERROR_MIN_HEIGHT = 120
_STATUS_INNER_SPACING = 8
_STATUS_INNER_MARGIN = 10

# Tray startup: log level default and main() dependency error
_DEFAULT_LOG_LEVEL = "NONE"
_LOG_LEVEL_CHOICES = ("NONE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_ERR_TRAY_DEPS = "Tray requires AppIndicator3 + GTK3 + PyGObject. On Arch: libappindicator, gtk3, libnotify, python-gobject."

# argparse: icon-style choices
_ICON_STYLE_CHOICES = (1, 2)


def _stop_fail_message(result):
    """Return error message string from request_stop() result (dict, str, or None)."""
    if isinstance(result, dict):
        return result.get(_STOP_RESPONSE_KEY_MESSAGE, _MSG_STOP_MAY_STILL_RUNNING)
    return str(result) if result is not None else _UNKNOWN_ERROR


def _tray_version():
    """Return package version string for display, or 'unknown' if unavailable."""
    try:
        from importlib.metadata import version
        return version(_APP_ID)
    except Exception:
        return "unknown"


# Status window General tab: state -> first-line status text
_STATUS_WINDOW_STATUS_TEXT = {
    DaemonState.LIMBO: _STATUS_WIN_LIMBO,
    DaemonState.SHUTTING_DOWN: _LABEL_SHUTTING_DOWN,
    DaemonState.INITIAL: _STATUS_WIN_INITIAL,
    DaemonState.SYNCING: _STATUS_WIN_SYNCING,
    DaemonState.CONFIG_CHANGED: _STATUS_WIN_CONFIG_CHANGED,
    DaemonState.CONFIG_INVALID: _STATUS_WIN_CONFIG_INVALID,
    DaemonState.SYNC_ISSUES: _STATUS_WIN_SYNC_ISSUES,
}


class DaemonManager:
    def __init__(self):
        self.daemon_start_error = None
        self.state_lock = Lock()
        # Show syncing icon until this monotonic time (so quick syncs always give visible feedback)
        self.sync_feedback_until = 0.0
        self._last_sync_timestamps = {}  # job_key -> last_sync string

    def update_sync_feedback(self, status):
        """If status shows SYNCING or a job's last_sync just changed, ensure syncing icon shows for MIN_SYNC_FEEDBACK_SECONDS."""
        with self.state_lock:
            now = time.monotonic()
            s = _as_status_dict(status)
            if not s:
                return
            if s.get(sp.CURRENTLY_SYNCING):
                self.sync_feedback_until = max(self.sync_feedback_until, now + MIN_SYNC_FEEDBACK_SECONDS)
            sync_jobs = _safe_status_dict(s, sp.SYNC_JOBS)
            for job_key, job_status in sync_jobs.items():
                if not isinstance(job_status, dict):
                    continue
                last_sync = job_status.get(sp.LAST_SYNC)
                last_sync_str = str(last_sync).strip() if last_sync is not None else ""
                prev = self._last_sync_timestamps.get(job_key, "")
                # Only show feedback when last_sync *changed* from a previous known value (not on first sight / tray restart)
                if prev and last_sync_str != prev:
                    self.sync_feedback_until = max(self.sync_feedback_until, now + MIN_SYNC_FEEDBACK_SECONDS)
                self._last_sync_timestamps[job_key] = last_sync_str

    def get_effective_state_for_display(self, status):
        """State to use for the tray icon. Derived from status at paint time (no cached current_state).
        Show SYNCING (blue) for min duration after a sync; never override error states with blue.
        """
        state = self.get_current_state(status)
        with self.state_lock:
            now = time.monotonic()
            in_feedback = self.sync_feedback_until > 0 and now < self.sync_feedback_until
            if in_feedback and state == DaemonState.RUNNING:
                return DaemonState.SYNCING
        return state

    def get_current_state(self, status):
        state = status_to_display_state(status, self.daemon_start_error)
        if state == DaemonState.FAILED:
            s = _as_status_dict(status)
            if status is not None and not s:
                self.daemon_start_error = _MSG_UNEXPECTED_STATUS_TYPE.format(type(status))
            elif s.get(sp.STATUS) == _STATUS_VALUE_ERROR:
                self.daemon_start_error = s.get(sp.MESSAGE, _UNKNOWN_ERROR_OCCURRED)
        return state

    def get_menu_spec(self, status):
        """Return a list of menu spec dicts (type, label, callback, enabled, submenu) for any backend."""
        current_state = self.get_current_state(status)
        spec = []

        if current_state == DaemonState.INITIAL:
            spec.append({"type": "item", "label": _LABEL_INITIALIZING, "callback": None, "enabled": False})
        elif current_state == DaemonState.FAILED:
            spec.extend(self._get_failed_spec(status))
        elif current_state == DaemonState.LIMBO:
            spec.extend(self._get_limbo_spec(status))
        elif current_state == DaemonState.OFFLINE:
            spec.extend(self._get_offline_spec(status))
        else:
            spec.extend(self._get_normal_spec(status))

        edit_config_enabled = current_state in _EDIT_CONFIG_STATES
        spec.extend([
            {"type": "separator"},
            {"type": "item", "label": _LABEL_CONFIG_AND_LOGS, "callback": None, "enabled": True, "submenu": [
                {"type": "item", "label": _LABEL_RELOAD_CONFIG, "callback": reload_config, "enabled": current_state not in _RELOAD_DISABLED_STATES},
                {"type": "item", "label": _LABEL_EDIT_CONFIG, "callback": edit_config, "enabled": edit_config_enabled},
                {"type": "item", "label": _LABEL_OPEN_CONFIG_FOLDER, "callback": open_config_file, "enabled": True},
                {"type": "item", "label": _LABEL_OPEN_LOG_FOLDER, "callback": open_log_folder, "enabled": True},
            ]},
            {"type": "separator"},
        ])
        spec.append({"type": "item", "label": _LABEL_SHOW_STATUS_WINDOW, "callback": show_status_window, "enabled": current_state != DaemonState.INITIAL})
        spec.append({"type": "separator"})

        if status is None:
            spec.append({"type": "item", "label": _LABEL_START_DAEMON, "callback": start_daemon, "enabled": True})
        elif current_state == DaemonState.SHUTTING_DOWN:
            spec.append({"type": "item", "label": _LABEL_SHUTTING_DOWN, "callback": None, "enabled": False})
        else:
            spec.append({"type": "item", "label": _LABEL_STOP_DAEMON, "callback": stop_daemon, "enabled": True})

        spec.append({"type": "item", "label": _LABEL_EXIT_TRAY, "callback": exit_tray, "enabled": True})
        return spec

    def _get_failed_spec(self, status):
        items = [{"type": "item", "label": _LABEL_DAEMON_NOT_RUNNING_WARN, "callback": None, "enabled": False}]
        err_from_status = _as_status_dict(status).get(sp.ERROR)
        error_message = err_from_status or self.daemon_start_error or _UNKNOWN_ERROR
        first_line = _truncate(str(error_message).split("\n")[0], _TRUNCATE_ERROR_LINE)
        items.append({"type": "item", "label": f"{_LABEL_ERROR_PREFIX} {first_line}", "callback": None, "enabled": False})
        if self.daemon_start_error or err_from_status:
            items.append({"type": "item", "label": _LABEL_SHOW_FULL_ERROR, "callback": lambda *a: show_text_window(_TITLE_DAEMON_ERROR_LOG, self.daemon_start_error or err_from_status or _UNKNOWN_ERROR), "enabled": True})
        return items

    def _get_offline_spec(self, status):
        """Offline menu: no job data so icon and menu stay consistent (grey + offline menu)."""
        items = [{"type": "item", "label": _LABEL_DAEMON_NOT_RUNNING, "callback": None, "enabled": False}]
        return items

    def _get_limbo_spec(self, status):
        items = [{"type": "item", "label": _LABEL_LIMBO_STATE, "callback": None, "enabled": False}]
        s = _as_status_dict(status)
        if s.get(sp.CONFIG_INVALID, False):
            items.append({"type": "item", "label": _LABEL_CONFIG_INVALID, "callback": None, "enabled": False})
            items.append({"type": "item", "label": f"{_LABEL_ERROR_PREFIX} {_truncate(s.get(sp.CONFIG_ERROR_MESSAGE) or _UNKNOWN_ERROR, _TRUNCATE_MENU_ERROR)}...", "callback": None, "enabled": False})
        if s.get(sp.CONFIG_CHANGED_ON_DISK, False):
            items.append({"type": "item", "label": _LABEL_CONFIG_CHANGED_DISK, "callback": None, "enabled": False})
        return items

    def _get_normal_spec(self, status):
        items = []
        s = _as_status_dict(status)
        if not s:
            return items
        if _has_sync_issues(status):
            items.append({"type": "item", "label": _LABEL_SYNC_ISSUES_DETECTED, "callback": None, "enabled": False})
        if s.get(sp.CONFIG_CHANGED_ON_DISK):
            items.append({"type": "item", "label": _LABEL_CONFIG_CHANGED_DISK, "callback": None, "enabled": False})
        if _has_sync_issues(status) or s.get(sp.CONFIG_CHANGED_ON_DISK):
            items.append({"type": "separator"})
        jobs = _currently_syncing_list(status)
        if jobs:
            items.append({"type": "item", "label": _LABEL_CURRENTLY_SYNCING, "callback": None, "enabled": False})
            for job in jobs:
                items.append({"type": "item", "label": f"  {str(job).strip()}", "callback": None, "enabled": False})
        queued_jobs = _safe_status_list(status, sp.QUEUED_PATHS)
        if queued_jobs:
            items.append({"type": "item", "label": _LABEL_QUEUED_JOBS, "callback": None, "enabled": False})
            for job in queued_jobs:
                items.append({"type": "item", "label": f"  {job}", "callback": None, "enabled": False})
        sync_jobs = _safe_status_dict(status, sp.SYNC_JOBS)
        if sync_jobs:
            jobs_submenu = []
            for job_key, job_status in sync_jobs.items():
                job_submenu = [
                    {"type": "item", "label": _LABEL_SYNC_NOW, "callback": create_sync_now_handler(job_key), "enabled": True},
                    {"type": "item", "label": _LABEL_FORCE_SYNC_NOW, "callback": create_sync_now_handler(job_key, force_bisync=True), "enabled": True},
                    {"type": "item", "label": _LABEL_RESYNC_SYNC_NOW, "callback": create_sync_now_handler(job_key, resync=True), "enabled": True},
                    {"type": "item", "label": f"{_LABEL_LAST_SYNC} {job_status.get(sp.LAST_SYNC) or _LABEL_NEVER}", "callback": None, "enabled": False},
                    {"type": "item", "label": f"{_LABEL_NEXT_RUN} {job_status.get(sp.NEXT_RUN) or _LABEL_NOT_SCHEDULED}", "callback": None, "enabled": False},
                    {"type": "item", "label": f"{_LABEL_SYNC_STATUS} {job_status.get(sp.SYNC_STATUS, _LABEL_NA)}", "callback": None, "enabled": False},
                    {"type": "item", "label": f"{_LABEL_RESYNC_STATUS} {job_status.get(sp.RESYNC_STATUS, _LABEL_NA)}", "callback": None, "enabled": False},
                ]
                jobs_submenu.append({"type": "item", "label": job_key, "callback": None, "enabled": True, "submenu": job_submenu})
            items.append({"type": "item", "label": _LABEL_SYNC_JOBS, "callback": None, "enabled": True, "submenu": jobs_submenu})
        else:
            items.append({"type": "item", "label": _LABEL_SYNC_JOBS, "callback": None, "enabled": False})
        return items

    def _icon_color_for_state(self, state):
        """Map DaemonState to tray icon color (GREEN=RUNNING, BLUE=SYNCING, RED=issues/failed, AMBER=config changed, PURPLE=shutdown/limbo, GRAY=offline, YELLOW=initial/starting)."""
        return _STATE_COLORS.get(state, Colors.GRAY)

    def _underlying_active_color_for_status(self, status):
        """Color we'd show if not shutting down/limbo (for top half of split icon)."""
        s = _as_status_dict(status)
        if not s:
            return Colors.GRAY
        if s.get(sp.CURRENTLY_SYNCING):
            return Colors.BLUE
        if s.get(sp.CONFIG_CHANGED_ON_DISK):
            return Colors.AMBER
        if _has_sync_issues(status):
            return Colors.RED
        if s.get(sp.CONFIG_INVALID):
            return Colors.RED
        if s.get(sp.RUNNING):
            return Colors.GREEN
        return Colors.GRAY


def _build_gtk_menu(spec):
    """Build Gtk.Menu from menu spec list (used by AppIndicator backend)."""
    if not APPINDICATOR_AVAILABLE:
        return None
    spec = spec if spec is not None and isinstance(spec, (list, tuple)) else []
    menu = Gtk.Menu()
    for s in spec:
        if not isinstance(s, dict):
            continue
        item_type = s.get(_SPEC_KEY_TYPE)
        if item_type == _SPEC_VALUE_SEPARATOR:
            menu.append(Gtk.SeparatorMenuItem())
        elif item_type == _SPEC_VALUE_ITEM:
            label = s.get(_SPEC_KEY_LABEL, "")
            item = Gtk.MenuItem.new_with_label(str(label))
            item.set_sensitive(s.get(_SPEC_KEY_ENABLED, True))
            if s.get(_SPEC_KEY_SUBMENU):
                sub = _build_gtk_menu(s[_SPEC_KEY_SUBMENU])
                item.set_submenu(sub)
            elif s.get(_SPEC_KEY_CALLBACK):
                cb = s[_SPEC_KEY_CALLBACK]
                item.connect("activate", lambda w, c=cb: c(w) if c else None)
            menu.append(item)
    menu.show_all()
    return menu


def _log_status_changed(status):
    """Log that daemon status changed (used by get_daemon_status and _apply_status_result)."""
    log_message(_LOG_STATUS_CHANGED, level=logging.INFO)
    try:
        log_message(f"New status: {json.dumps(status, default=str)[:_TRUNCATE_DEBUG_STATUS]}...", level=logging.DEBUG)
    except (TypeError, ValueError):
        log_message(_LOG_STATUS_SERIALIZE_FAIL, level=logging.DEBUG)


def get_daemon_status():
    """Blocking fetch: request status and update state.last_status. Used at startup only; UI uses state.last_status (no re-fetch)."""
    state, _ = _get_tray_state_and_daemon()
    if state is None:
        return None
    try:
        status = request_status(timeout=_REQUEST_STATUS_TIMEOUT, retries=_REQUEST_STATUS_RETRIES, retry_delay=_REQUEST_STATUS_RETRY_DELAY)
        if status is None:
            return None
        with state.last_status_lock:
            changed = status != state.last_status
            state.last_status = status
            if changed:
                _log_status_changed(status)
        return status
    except Exception as e:
        log_message(_LOG_ERR_COMMUNICATING_DAEMON.format(str(e)), level=logging.ERROR)
        return None


def _apply_status_result(state, status):
    """Apply a status result from a worker: update last_status, offline_miss_count, log, and queue UI refresh."""
    try:
        if status is not None:
            state.offline_miss_count = 0
            state.daemon_manager.update_sync_feedback(status)
            with state.last_status_lock:
                changed = status != state.last_status
                had_status = state.last_status is not None
                state.last_status = status
            if changed:
                _log_status_changed(status)
                state.update_queue.put(True)
        else:
            state.offline_miss_count += 1
            if state.offline_miss_count >= OFFLINE_CLEAR_AFTER_MISSES:
                with state.last_status_lock:
                    had_status = state.last_status is not None
                    state.last_status = None
                # Only refresh when we actually transition to OFFLINE (was having status before)
                if had_status:
                    state.update_queue.put(True)
    except Exception as e:
        log_message(_LOG_ERR_APPLYING_STATUS.format(e), level=logging.ERROR)


def _status_fetch_worker(state):
    """Run in a thread: blocking request_status so the poll loop never blocks on the socket.
    If the poll loop blocked here, no further log lines (e.g. 'Daemon status changed') would appear
    until the daemon responded. Running the fetch in a worker avoids that."""
    try:
        status = request_status(timeout=_REQUEST_STATUS_TIMEOUT, retries=_REQUEST_STATUS_RETRIES, retry_delay=_REQUEST_STATUS_RETRY_DELAY)
    except Exception as e:
        log_message(_LOG_ERR_FETCHING_STATUS.format(e), level=logging.ERROR)
        status = None
    finally:
        _status_fetch_in_progress[0] = False
    _apply_status_result(state, status)


def create_sync_now_handler(job_key, force_bisync=False, resync=False):
    """Return a menu callback that accepts (widget) from GTK activate signal."""
    def handler(widget=None):
        success = add_to_sync_queue(job_key, force_bisync, resync)
        if not success:
            show_notification(_NOTIFY_SYNC_ERROR_TITLE, _NOTIFY_SYNC_ERROR_BODY.format(job_key))
    return handler


def stop_daemon(widget=None):
    def _wait_then_refresh():
        for _ in range(_STOP_POLL_ATTEMPTS):
            time.sleep(_STOP_POLL_INTERVAL)
            if request_status(timeout=_STOP_POLL_TIMEOUT) is None:
                break
        GLib.idle_add(update_menu_and_icon)

    fail_msg = None
    try:
        result = request_stop(timeout=_STOP_REQUEST_TIMEOUT, retries=_STOP_REQUEST_RETRIES, retry_delay=_STOP_REQUEST_RETRY_DELAY)
        if isinstance(result, dict) and result.get(_STOP_RESPONSE_KEY_STATUS) == _STOP_RESULT_SUCCESS:
            log_message(_LOG_STOP_PROGRESS)
            show_notification(_NOTIFY_STOP_TITLE, _NOTIFY_STOP_BODY)
            Thread(target=_wait_then_refresh, daemon=True).start()
        else:
            fail_msg = _stop_fail_message(result)
    except Exception as e:
        fail_msg = str(e)
    if fail_msg is not None:
        log_message(_LOG_ERR_STOP_DAEMON.format(fail_msg), level=logging.ERROR)
        show_notification(_NOTIFY_STOP_FAIL_TITLE, fail_msg)
        update_menu_and_icon()


def _log_daemon_start_done(state, already_up):
    """Log after start_daemon subprocess wait. If already_up is None, check get_daemon_status() first.
    When daemon is already responding, log at DEBUG to avoid noisy INFO."""
    if already_up is None:
        already_up = get_daemon_status() is not None
    if already_up:
        log_message(_LOG_START_ALREADY_RESPONDING, level=logging.DEBUG)
    else:
        log_message(_LOG_START_REQUESTED, level=logging.INFO)
        log_message(_LOG_START_TRAY_WILL_SHOW, level=logging.DEBUG)


def start_daemon(widget=None):
    state, dm = _get_tray_state_and_daemon()
    if state is None:
        log_message(_LOG_DAEMON_MANAGER_UNAVAILABLE, level=logging.ERROR)
        return
    # Check if the daemon is already running (use stored status to avoid blocking)
    with state.last_status_lock:
        current_status = state.last_status
    if current_status is not None:
        log_message(_LOG_START_ALREADY_RUNNING, level=logging.INFO)
        show_notification(_NOTIFY_ALREADY_RUNNING_TITLE, _NOTIFY_ALREADY_RUNNING_BODY)
        state.update_queue.put(True)
        return

    cleared = clear_crash_log()
    if cleared:
        log_message(_LOG_CLEARED_CRASH_LOG, level=logging.INFO)
    dm.daemon_start_error = None

    start_fail_full = None
    start_fail_short = None
    try:
        log_message(_LOG_START_ATTEMPTING, level=logging.DEBUG)
        command = [_APP_ID, _CMD_DAEMON, _CMD_START]
        if getattr(state.args, "config", None):
            command.extend([_ARG_CONFIG, state.args.config])
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        try:
            stdout, stderr = process.communicate(timeout=_DAEMON_START_WAIT_TIMEOUT)
            if process.returncode is not None:
                if process.returncode != 0:
                    raise subprocess.CalledProcessError(
                        process.returncode, process.args, stdout, stderr)
                log_message(_LOG_STARTED_SUCCESS, level=logging.INFO)
            else:
                _log_daemon_start_done(state, already_up=None)
        except subprocess.TimeoutExpired:
            _log_daemon_start_done(state, already_up=None)
        state.update_queue.put(True)
    except subprocess.CalledProcessError as e:
        start_fail_full = f"{_START_ERR_PREFIX} return code {e.returncode}\nstdout: {e.stdout}\nstderr: {e.stderr}"
        start_fail_short = _truncate(e.stderr or e.stdout or str(e), _TRUNCATE_START_FAIL) or _LOG_EXIT_CODE.format(e.returncode)
    except Exception as e:
        start_fail_full = f"{_START_ERR_UNEXPECTED_PREFIX} {e}\n{traceback.format_exc()}"
        start_fail_short = _truncate(str(e), _TRUNCATE_START_FAIL)
    if start_fail_full is not None:
        log_message(start_fail_full, level=logging.ERROR)
        dm.daemon_start_error = start_fail_full
        show_notification(_NOTIFY_START_FAIL_TITLE, start_fail_short)
        state.update_queue.put(True)


def _truncate(s, maxlen=_TRUNCATE_START_FAIL):
    """Return str(s) truncated to maxlen if longer."""
    s = str(s)
    return s[:maxlen] if len(s) > maxlen else s


def _str_or_empty(x):
    """Return str(x) or "" if x is None."""
    return str(x) if x is not None else ""


def _safe_status_dict(status, key):
    """Return status[key] as a dict, or {} if status/key missing or not a dict."""
    if not isinstance(status, dict):
        return {}
    val = status.get(key)
    return val if isinstance(val, dict) else {}


def _safe_status_list(status, key):
    """Return status[key] as a list, or [] if status/key missing or not a list/tuple."""
    if not isinstance(status, dict):
        return []
    val = status.get(key, [])
    return list(val) if isinstance(val, (list, tuple)) else []


def _as_status_dict(status):
    """Return status as a dict for safe .get() use, or {} if not a dict."""
    return status if isinstance(status, dict) else {}


def _currently_syncing_list(status):
    """Return list of currently syncing job names (status may have string or list)."""
    if not isinstance(status, dict):
        return []
    v = status.get(sp.CURRENTLY_SYNCING)
    if not v:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _reload_config_fail(state, log_msg, notify_body):
    """Log, notify, queue refresh, return False. Used by reload_config on failure."""
    log_message(log_msg, level=logging.ERROR)
    show_notification(_NOTIFY_RELOAD_FAIL_TITLE, _truncate(notify_body))
    state.update_queue.put(True)
    return False


def reload_config(widget=None):
    """Reload daemon config. Accepts optional widget arg from GTK menu activate signal."""
    state, _ = _get_tray_state_and_daemon()
    if state is None:
        return False
    try:
        response_data = request_reload()
        if response_data is None:
            return _reload_config_fail(state, _RELOAD_ERR_DAEMON_NOT_RUNNING, _RELOAD_NOTIFY_DAEMON_NOT_RUNNING)
        if not isinstance(response_data, dict):
            return _reload_config_fail(state, _RELOAD_ERR_UNEXPECTED_RESPONSE, _RELOAD_NOTIFY_UNEXPECTED_RESPONSE)
        if response_data.get(sp.STATUS) == _RELOAD_STATUS_SUCCESS:
            log_message(_LOG_RELOAD_SUCCESS)
            show_notification(_NOTIFY_RELOAD_SUCCESS_TITLE, _NOTIFY_RELOAD_SUCCESS_BODY)
            state.update_queue.put(True)
            return True
        msg = response_data.get(sp.MESSAGE, _UNKNOWN_ERROR)
        return _reload_config_fail(state, _RELOAD_ERR_PREFIX.format(msg), msg)
    except Exception as e:
        return _reload_config_fail(state, _LOG_ERR_COMMUNICATING_DAEMON.format(str(e)), str(e))


def add_to_sync_queue(job_key, force_bisync=False, resync=False):
    state, _ = _get_tray_state_and_daemon()
    if state is None:
        return False
    try:
        response = request_add_sync(job_key, force_bisync=force_bisync, resync=resync)
        log_message(f"Add to sync queue response: {response}", level=logging.DEBUG)
        state.update_queue.put(True)
        if response == _SYNC_QUEUE_RESPONSE_OK:
            show_notification(_NOTIFY_SYNC_QUEUED_TITLE, _NOTIFY_SYNC_QUEUED_BODY.format(job_key))
            return True
        return False
    except Exception as e:
        log_message(_LOG_ERR_ADD_SYNC_QUEUE.format(str(e)), level=logging.ERROR)
        state.update_queue.put(True)
        return False


def _normalize_icon_color_and_thickness(color, thickness):
    """Return (hex_color_str, int_thickness) for SVG icon rendering."""
    if isinstance(color, tuple) and len(color) >= 3:
        hex_color = '#{:02x}{:02x}{:02x}'.format(color[0], color[1], color[2])
    else:
        hex_color = _HEX_GRAY
    thick = int(thickness) if thickness is not None else _DEFAULT_ICON_THICKNESS
    return hex_color, thick


_ICON_SIZE = 64


def _render_svg_icon(svg_template, color, thickness, size=_ICON_SIZE):
    """Render SVG template (with {color}, {thickness} placeholders) to RGBA Image."""
    color, thickness = _normalize_icon_color_and_thickness(color, thickness)
    svg_code = svg_template.format(color=color, thickness=thickness)
    png_data = svg2png(bytestring=svg_code.encode('utf-8'), output_width=size, output_height=size)
    return Image.open(BytesIO(png_data)).convert('RGBA')


def create_status_image_style1(color, thickness):
    svg = '''
    <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
    <path d="M505.6 57.6a20.906667 20.906667 0 0 1 6.4 15.36V170.666667a341.333333 341.333333 0 0 1 295.253333 512 22.186667 22.186667 0 0 1-15.786666 10.24 21.333333 21.333333 0 0 1-17.92-5.973334l-31.146667-31.146666a21.333333 21.333333 0 0 1-3.84-25.173334A253.44 253.44 0 0 0 768 512a256 256 0 0 0-256-256v100.693333a20.906667 20.906667 0 0 1-6.4 15.36l-8.533333 8.533334a21.333333 21.333333 0 0 1-30.293334 0L315.733333 229.973333a21.76 21.76 0 0 1 0-30.293333l151.04-150.613333a21.333333 21.333333 0 0 1 30.293334 0z m51.626667 585.813333a21.333333 21.333333 0 0 0-30.293334 0l-8.533333 8.533334a20.906667 20.906667 0 0 0-6.4 15.36V768a256 256 0 0 1-256-256 248.746667 248.746667 0 0 1 29.866667-119.04 21.76 21.76 0 0 0-3.84-25.173333l-31.573334-31.573334a21.333333 21.333333 0 0 0-17.92-5.973333 22.186667 22.186667 0 0 0-15.786666 11.093333A341.333333 341.333333 0 0 0 512 853.333333v97.706667a20.906667 20.906667 0 0 0 6.4 15.36l8.533333 8.533333a21.333333 21.333333 0 0 0 30.293334 0l151.04-150.613333a21.76 21.76 0 0 0 0-30.293333z" 
    fill="{color}" stroke="{color}" stroke-width="{thickness}" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>
    '''
    return _render_svg_icon(svg, color, thickness)


def create_status_image_style2(color, thickness):
    svg = '''
    <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
    <path d="M917.333 394.667H106.667a32 32 0 0 1 0-64h810.666a32 32 0 0 1 0 64z m0 298.666H106.667a32 32 0 0 1 0-64h810.666a32 32 0 0 1 0 64z" fill="none" stroke="{color}" stroke-width="{thickness}" stroke-linecap="round"/>
    <path d="M106.667 394.667a32 32 0 0 1-22.614-54.614l241.28-241.28A32 32 0 0 1 370.56 144L129.28 385.28a32 32 0 0 1-22.613 9.387z m569.386 539.946A32 32 0 0 1 653.44 880l241.28-241.28a32 32 0 1 1 45.227 45.227l-241.28 241.28a32 32 0 0 1-22.614 9.386z" fill="none" stroke="{color}" stroke-width="{thickness}" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    '''
    return _render_svg_icon(svg, color, thickness)


def _composite_icon_top_bottom(img_top, img_bottom):
    """Composite two same-size RGBA images: top half from img_top, bottom half from img_bottom."""
    w, h = img_top.size
    result = img_top.copy()
    mask = Image.new("L", (w, h), 0)
    for y in range(h // 2, h):
        for x in range(w):
            mask.putpixel((x, y), 255)
    result.paste(img_bottom, (0, 0), mask)
    return result


def create_status_image(color, style=1, thickness=_DEFAULT_ICON_THICKNESS, bottom_color=None):
    """If bottom_color is set, draw icon with top half = color, bottom half = bottom_color (e.g. shutdown transition)."""
    make_img = create_status_image_style2 if style == 2 else create_status_image_style1
    img = make_img(color, thickness)
    if bottom_color is not None:
        img = _composite_icon_top_bottom(img, make_img(bottom_color, thickness))
    return img


def _make_refresh_status_cb(win):
    """Return a callback that destroys win and reopens the status window (for Refresh button)."""
    return lambda b: (win.destroy(), GLib.idle_add(_show_status_window_gtk))


def _show_status_window_gtk():
    """GTK status window (AppIndicator path only). Uses stored last_status (no blocking fetch)."""
    state, dm = _get_tray_state_and_daemon()
    if not APPINDICATOR_AVAILABLE or state is None:
        return
    if state.status_window_gtk is not None and state.status_window_gtk.get_visible():
        state.status_window_gtk.present()
        return
    with state.last_status_lock:
        raw_status = state.last_status
    status = _as_status_dict(raw_status)
    current_state = dm.get_current_state(raw_status)

    state_title = _STATE_DISPLAY_NAMES.get(current_state, _LABEL_STATUS_FALLBACK)
    win = Gtk.Window(title=f"{_LABEL_STATUS_WINDOW_TITLE}{state_title}")
    win.set_default_size(*_STATUS_WINDOW_SIZE)
    state.status_window_gtk = win

    def _on_status_win_destroy(w):
        state.status_window_gtk = None

    win.connect("destroy", _on_status_win_destroy)

    if current_state in _STATES_NO_DAEMON:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=_STATUS_BOX_SPACING)
        box.set_margin_start(_STATUS_BOX_MARGIN)
        box.set_margin_end(_STATUS_BOX_MARGIN)
        box.set_margin_top(_STATUS_BOX_MARGIN)
        box.set_margin_bottom(_STATUS_BOX_MARGIN)
        win.add(box)
        box.pack_start(Gtk.Label(label=f"{_LABEL_VERSION_LINE} {_tray_version()}", xalign=0), False, False, 0)
        lbl = Gtk.Label(label=_LABEL_DAEMON_NOT_RUNNING_WARN)
        lbl.get_style_context().add_class(_CSS_CLASS_ERROR)
        lbl.set_xalign(0)
        box.pack_start(lbl, False, False, 0)
        if dm.daemon_start_error:
            sw = Gtk.ScrolledWindow()
            sw.set_min_content_height(_STATUS_ERROR_MIN_HEIGHT)
            tv = Gtk.TextView()
            tv.set_editable(False)
            tv.get_buffer().set_text(_str_or_empty(dm.daemon_start_error))
            sw.add(tv)
            box.pack_start(sw, True, True, 0)
        btn_box = Gtk.Box(spacing=_STATUS_INNER_SPACING)
        btn = Gtk.Button(label=_LABEL_START_DAEMON)
        def _on_start_clicked(b):
            start_daemon()
            lbl.set_label(_LABEL_STARTING_DAEMON)
            b.set_sensitive(False)
        btn.connect("clicked", _on_start_clicked)
        btn_box.pack_start(btn, False, False, 0)
        btn_refresh = Gtk.Button(label=_LABEL_BUTTON_REFRESH)
        btn_refresh.connect("clicked", _make_refresh_status_cb(win))
        btn_box.pack_start(btn_refresh, False, False, 0)
        box.pack_start(btn_box, False, False, 0)
    else:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=_STATUS_INNER_SPACING)
        outer.set_margin_top(_STATUS_INNER_MARGIN)
        outer.set_margin_bottom(_STATUS_INNER_MARGIN)
        outer.set_margin_start(_STATUS_INNER_MARGIN)
        outer.set_margin_end(_STATUS_INNER_MARGIN)
        win.add(outer)
        nb = Gtk.Notebook()
        outer.pack_start(nb, True, True, 0)
        btn_refresh = Gtk.Button(label=_LABEL_BUTTON_REFRESH)
        btn_refresh.connect("clicked", _make_refresh_status_cb(win))
        outer.pack_start(btn_refresh, False, False, 0)
        outer.pack_start(Gtk.Label(label=_LABEL_CLICK_REFRESH, xalign=0), False, False, 0)
        gen_sw = Gtk.ScrolledWindow()
        gen_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=_STATUS_INNER_SPACING)
        gen_sw.add(gen_box)
        nb.append_page(gen_sw, Gtk.Label(label=_LABEL_TAB_GENERAL))
        status_text = _STATUS_WINDOW_STATUS_TEXT.get(current_state, _LABEL_DAEMON_RUNNING)
        gen_box.pack_start(Gtk.Label(label=status_text, xalign=0), False, False, 0)
        version_val = status.get(sp.VERSION) or _tray_version()
        gen_box.pack_start(Gtk.Label(label=f"{_LABEL_VERSION_LINE} {version_val}", xalign=0), False, False, 0)
        pid_val = status.get(sp.PID)
        if pid_val is not None:
            gen_box.pack_start(Gtk.Label(label=f"{_LABEL_PID_LINE} {pid_val}", xalign=0), False, False, 0)
        gen_box.pack_start(Gtk.Label(label=f"{_LABEL_CONFIG_LINE} {_LABEL_VALID if not status.get(sp.CONFIG_INVALID, False) else _LABEL_INVALID}", xalign=0), False, False, 0)
        gen_box.pack_start(Gtk.Label(label=f"{_LABEL_CONFIG_CHANGED_DISK_LINE} {_LABEL_YES if status.get(sp.CONFIG_CHANGED_ON_DISK, False) else _LABEL_NO}", xalign=0), False, False, 0)
        cfg_path = status.get(sp.CONFIG_FILE_LOCATION)
        if cfg_path:
            gen_box.pack_start(Gtk.Label(label=f"{_LABEL_CONFIG_FILE_LINE} {cfg_path}", xalign=0), False, False, 0)
        log_path = status.get(sp.LOG_FILE_LOCATION)
        if log_path:
            gen_box.pack_start(Gtk.Label(label=f"{_LABEL_LOG_FILE_LINE} {log_path}", xalign=0), False, False, 0)
        gen_box.pack_start(Gtk.Label(label=_LABEL_CURRENTLY_SYNCING, xalign=0), False, False, 0)
        gen_box.pack_start(Gtk.Label(label=str(status.get(sp.CURRENTLY_SYNCING, _LABEL_NONE)), xalign=0), False, False, 0)
        gen_box.pack_start(Gtk.Label(label=_LABEL_QUEUED_JOBS, xalign=0), False, False, 0)
        _queued = _safe_status_list(status, sp.QUEUED_PATHS)
        for j in _queued:
            gen_box.pack_start(Gtk.Label(label=f"  {j}", xalign=0), False, False, 0)
        if not _queued:
            gen_box.pack_start(Gtk.Label(label=_LABEL_NONE, xalign=0), False, False, 0)
        # Sync Jobs
        jobs_sw = Gtk.ScrolledWindow()
        jobs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=_STATUS_INNER_SPACING)
        jobs_sw.add(jobs_box)
        nb.append_page(jobs_sw, Gtk.Label(label=_LABEL_TAB_SYNC_JOBS))
        sync_jobs_dict = _safe_status_dict(status, sp.SYNC_JOBS)
        if sync_jobs_dict:
            for job_key, job_status in sync_jobs_dict.items():
                fr = Gtk.Frame(label=str(job_key))
                fr_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=_STATUS_FRAME_BOX_SPACING)
                fr.add(fr_box)
                fr_box.pack_start(Gtk.Label(label=f"{_LABEL_LAST_SYNC} {job_status.get(sp.LAST_SYNC, _LABEL_NA)}", xalign=0), False, False, 0)
                fr_box.pack_start(Gtk.Label(label=f"{_LABEL_NEXT_RUN} {job_status.get(sp.NEXT_RUN, _LABEL_NA)}", xalign=0), False, False, 0)
                fr_box.pack_start(Gtk.Label(label=f"{_LABEL_SYNC_STATUS} {job_status.get(sp.SYNC_STATUS, _LABEL_NA)}", xalign=0), False, False, 0)
                fr_box.pack_start(Gtk.Label(label=f"{_LABEL_RESYNC_STATUS} {job_status.get(sp.RESYNC_STATUS, _LABEL_NA)}", xalign=0), False, False, 0)
                jobs_box.pack_start(fr, False, False, 0)
        else:
            jobs_box.pack_start(Gtk.Label(label=_LABEL_NO_SYNC_JOBS, xalign=0), False, False, 0)
        # Sync Errors
        err_sw = Gtk.ScrolledWindow()
        err_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=_STATUS_INNER_SPACING)
        err_sw.add(err_box)
        nb.append_page(err_sw, Gtk.Label(label=_LABEL_TAB_SYNC_ERRORS))
        sync_errors = _safe_status_dict(status, sp.SYNC_ERRORS)
        if sync_errors:
            for path, err in sync_errors.items():
                fr = Gtk.Frame(label=str(path))
                fr_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=_STATUS_FRAME_BOX_SPACING)
                fr.add(fr_box)
                err_dict = err if isinstance(err, dict) else {}
                for k, v in err_dict.items():
                    fr_box.pack_start(Gtk.Label(label=f"{k}: {v}", xalign=0), False, False, 0)
                err_box.pack_start(fr, False, False, 0)
        else:
            err_box.pack_start(Gtk.Label(label=_LABEL_NO_SYNC_ERRORS, xalign=0), False, False, 0)
        # Config
        cfg_sw = Gtk.ScrolledWindow()
        cfg_tv = Gtk.TextView()
        cfg_tv.set_editable(False)
        cfg_sw.add(cfg_tv)
        nb.append_page(cfg_sw, Gtk.Label(label=_LABEL_TAB_CONFIG))
        cfg_path = status.get(sp.CONFIG_FILE_LOCATION)
        if cfg_path and os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8", errors="replace") as f:
                cfg_tv.get_buffer().set_text(f.read())
        else:
            cfg_tv.get_buffer().set_text(_MSG_CONFIG_NOT_FOUND)
    win.show_all()


def show_status_window(widget=None):
    _show_status_window_gtk()


def _open_directory(dir_path):
    """Open a directory in the system file manager (platform-dependent)."""
    if not dir_path:
        return
    if os.name == 'nt':
        os.startfile(dir_path)
    else:
        subprocess.call((_CMD_XDG_OPEN, dir_path))


def _require_path(path, log_msg, notify_title=None):
    """If path is falsy, log log_msg, optionally show notification (if notify_title), and return False; else return True."""
    if path:
        return True
    log_message(log_msg, level=logging.ERROR)
    if notify_title is not None:
        show_notification(notify_title, _MSG_PATH_UNAVAILABLE)
    return False


def open_config_file(widget=None):
    path = get_config_file_path()
    if not _require_path(path, _LOG_MSG_CONFIG_PATH_NOT_FOUND, _NOTIFY_CONFIG_FOLDER_TITLE):
        return
    _open_directory(os.path.dirname(path))


def open_log_folder(widget=None):
    path = get_log_file_path()
    if not _require_path(path, _LOG_MSG_LOG_PATH_NOT_FOUND, _NOTIFY_LOG_FOLDER_TITLE):
        return
    log_dir = os.path.dirname(path)
    if not log_dir:
        log_message(_LOG_LOG_PATH_NO_DIR, level=logging.INFO)
        show_notification(_NOTIFY_LOG_FOLDER_TITLE, _MSG_LOG_NO_DIR)
        return
    _open_directory(log_dir)


def _get_status_path(key):
    """Return status[key] from stored last_status (no blocking fetch). Used for config/log paths."""
    state, _ = _get_tray_state_and_daemon()
    if state is None:
        return None
    with state.last_status_lock:
        status = state.last_status
    return _as_status_dict(status).get(key) if status is not None else None


def get_config_file_path():
    return _get_status_path(sp.CONFIG_FILE_LOCATION)


def get_log_file_path():
    return _get_status_path(sp.LOG_FILE_LOCATION)


def _show_text_window_gtk(title, content):
    """GTK text window (AppIndicator path only)."""
    if not APPINDICATOR_AVAILABLE:
        return
    win = Gtk.Window(title=_str_or_empty(title))
    win.set_default_size(*_TEXT_WINDOW_SIZE)
    sw = Gtk.ScrolledWindow()
    tv = Gtk.TextView()
    tv.set_editable(False)
    tv.set_wrap_mode(Gtk.WrapMode.WORD)
    tv.get_buffer().set_text(_str_or_empty(content))
    sw.add(tv)
    win.add(sw)
    win.show_all()


def show_text_window(title, content):
    _show_text_window_gtk(title, content)


def _write_tray_icon_to_path(path, display_state, status=None):
    """Write status image to path (for AppIndicator). display_state is derived at paint time from fresh status.
    For SHUTTING_DOWN/LIMBO, status is used to get the top-half color (underlying active state); bottom half is grey."""
    tray_state, dm = _get_tray_state_and_daemon()
    if tray_state is None or tray_state.args is None:
        return
    try:
        style = tray_state.args.icon_style
        thickness = tray_state.args.icon_thickness
        if display_state in (DaemonState.SHUTTING_DOWN, DaemonState.LIMBO) and status is not None:
            top_color = dm._underlying_active_color_for_status(status)
            bottom_color = Colors.GRAY
            img = create_status_image(
                top_color, style=style, thickness=thickness, bottom_color=bottom_color
            )
        else:
            color = dm._icon_color_for_state(display_state)
            img = create_status_image(color, style=style, thickness=thickness)
        img.save(path, _ICON_FORMAT)
    except Exception as e:
        log_message(_LOG_ERR_WRITING_ICON.format(e), level=logging.ERROR)


def _update_appindicator_ui():
    """Rebuild indicator menu and icon (run on main thread via GLib.idle_add).
    Uses stored display status only (single source of truth); no fetch here.
    """
    state, dm = _get_tray_state_and_daemon()
    try:
        if state is None or state.indicator is None or not state.icon_paths:
            return False
        with state.last_status_lock:
            status = state.last_status
        if status is not None:
            dm.update_sync_feedback(status)
        display_state = dm.get_effective_state_for_display(status)
        # Unique path every time so AppIndicator cannot cache: always reloads the new icon
        tmp = tempfile.gettempdir()
        path = os.path.join(tmp, f"{_TRAY_ICON_PREFIX}{state.icon_counter}{_ICON_EXT}")
        state.icon_counter += 1
        _write_tray_icon_to_path(path, display_state, status=status)
        if hasattr(state.indicator, "set_icon_full"):
            state.indicator.set_icon_full(path, _ICON_DESC_STATUS.format(_APP_ID))
        else:
            state.indicator.set_icon(path)
        status_enum = AppIndicator3.IndicatorStatus
        state.indicator.set_status(status_enum.ATTENTION)
        state.indicator.set_status(status_enum.ACTIVE)
        spec = dm.get_menu_spec(status)
        menu = _build_gtk_menu(spec)
        if menu is not None:
            state.indicator.set_menu(menu)
    except Exception as e:
        log_message(_LOG_ERR_UPDATING_UI.format(e), level=logging.ERROR)
        log_message(_LOG_ERR_DETAILS.format(traceback.format_exc()), level=logging.DEBUG)
    return False  # GLib.idle_add: return False to remove source


def run_tray_appindicator():
    """Run tray using AppIndicator3 (SNI) + GTK (notifications, status window, config editor)."""
    state = TrayState()
    state.daemon_manager = DaemonManager()
    parser = argparse.ArgumentParser()
    parser.add_argument("--icon-style", type=int, choices=_ICON_STYLE_CHOICES, default=1)
    parser.add_argument("--icon-thickness", type=int, default=_DEFAULT_ICON_THICKNESS)
    parser.add_argument("--log-level", type=str, choices=_LOG_LEVEL_CHOICES, default=_DEFAULT_LOG_LEVEL)
    parser.add_argument("--enable-experimental", action="store_true")
    parser.add_argument(_ARG_CONFIG, type=str, default=get_default_config_file(),
                        help="Config file path (default: same XDG path as CLI)")
    state.args = parser.parse_args()
    state.update_queue = Queue()
    state.last_status = None
    state.last_status_lock = Lock()
    set_tray_state(state)

    minimal = type("TrayLogConfig", (), {})()
    minimal.console_log = state.args.log_level != _DEFAULT_LOG_LEVEL
    minimal.log_file_path = None
    minimal.min_console_level = getattr(logging, state.args.log_level) if state.args.log_level != _DEFAULT_LOG_LEVEL else (logging.CRITICAL + 1)
    set_config(minimal)
    setup_loggers(console_log=minimal.console_log)

    cleared = clear_crash_log()
    if cleared:
        log_message(_LOG_CLEARED_CRASH_LOG, level=logging.INFO)
    initial_status = get_daemon_status()
    with state.last_status_lock:
        state.last_status = initial_status
    if initial_status is not None:
        state.daemon_manager.update_sync_feedback(initial_status)
    initial_state = state.daemon_manager.get_effective_state_for_display(initial_status)

    tmp = tempfile.gettempdir()
    state.icon_paths = [os.path.join(tmp, f"{_TRAY_ICON_PREFIX}0{_ICON_EXT}")]
    state.icon_counter = 2  # first update will use ...-2.png so indicator sees a new path
    _write_tray_icon_to_path(state.icon_paths[0], initial_state)
    state.indicator = AppIndicator3.Indicator.new(
        _APP_ID,
        state.icon_paths[0],
        AppIndicator3.IndicatorCategory.SYSTEM_SERVICES,
    )
    state.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
    state.indicator.set_menu(_build_gtk_menu(state.daemon_manager.get_menu_spec(initial_status)))

    def on_update_queue():
        GLib.idle_add(_update_appindicator_ui)

    def handle_updates_appindicator():
        while True:
            try:
                state.update_queue.get()
                on_update_queue()
            except Exception as e:
                log_message(_LOG_ERR_HANDLE_UPDATES.format(e), level=logging.ERROR)
            finally:
                try:
                    state.update_queue.task_done()
                except ValueError:
                    pass

    Thread(target=check_status_and_update, daemon=True).start()
    Thread(target=handle_updates_appindicator, daemon=True).start()

    if initial_state == DaemonState.OFFLINE:
        Thread(target=start_daemon, daemon=True).start()

    try:
        Gtk.main()
    except KeyboardInterrupt:
        exit_tray()


def update_menu_and_icon():
    state, _ = _get_tray_state_and_daemon()
    if state is None:
        return
    GLib.idle_add(_update_appindicator_ui)


def check_status_and_update():
    """Poll loop: crash log, sync feedback expiry, and start a non-blocking status fetch worker.
    The worker runs request_status() in a thread so this loop never blocks on the socket; otherwise
    the log would stall until the daemon responded (e.g. after the first sync)."""
    while True:
        try:
            state, _ = _get_tray_state_and_daemon()
            if state is None:
                time.sleep(_POLL_LOOP_SLEEP_SECONDS)
                continue
            crash_message = read_crash_log()
            if crash_message:
                crash_message = str(crash_message).strip()
                if state.daemon_manager.daemon_start_error != crash_message:
                    state.daemon_manager.daemon_start_error = crash_message
                    state.update_queue.put(True)
                    log_message(_LOG_DAEMON_CRASHED, level=logging.ERROR)
                    log_message(_LOG_CRASH_MESSAGE.format(crash_message), level=logging.ERROR)
                time.sleep(_POLL_LOOP_SLEEP_SECONDS)
                continue

            # Clear expired feedback and trigger one more icon update when it expires
            with state.daemon_manager.state_lock:
                if state.daemon_manager.sync_feedback_until > 0 and time.monotonic() >= state.daemon_manager.sync_feedback_until:
                    state.daemon_manager.sync_feedback_until = 0
                    state.update_queue.put(True)

            # Start a status fetch in a worker so we never block here on the socket
            with _status_fetch_lock:
                if not _status_fetch_in_progress[0]:
                    _status_fetch_in_progress[0] = True
                    Thread(target=_status_fetch_worker, args=(state,), daemon=True).start()

        except Exception as e:
            log_message(_LOG_ERR_CHECK_STATUS.format(e), level=logging.ERROR)
            log_message(_LOG_ERR_DETAILS.format(traceback.format_exc()), level=logging.DEBUG)

        time.sleep(_POLL_LOOP_SLEEP_SECONDS)


def _show_error_dialog(text):
    """Show a modal error dialog (AppIndicator path)."""
    if not APPINDICATOR_AVAILABLE:
        return
    dlg = Gtk.MessageDialog(
        transient_for=None, flags=0,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.OK,
        text=_str_or_empty(text),
    )
    dlg.run()
    dlg.destroy()


def edit_config(widget=None):
    state, _ = _get_tray_state_and_daemon()
    if state is None:
        log_message(_LOG_DAEMON_MANAGER_UNAVAILABLE, level=logging.ERROR)
        return
    try:
        config_file = get_config_file_path()
        if not _require_path(config_file, _MSG_CONFIG_PATH_UNAVAILABLE, None):
            _show_error_dialog(_MSG_CONFIG_PATH_UNAVAILABLE)
            return
        from rclone_bisync_manager.config_editor import edit_config_gtk
        edit_config_gtk(config_file)
        reload_config()
    except Exception as e:
        log_message(_LOG_ERR_EDITING_CONFIG.format(str(e)), level=logging.ERROR)
        _show_error_dialog(_MSG_EDIT_CONFIG_FAIL.format(e))


def exit_tray(widget=None):
    log_message(_LOG_EXITING_TRAY, level=logging.INFO)
    Gtk.main_quit()
    sys.exit(0)


def show_notification(title, message):
    title = _str_or_empty(title)
    message = _str_or_empty(message)
    if NOTIFY_AVAILABLE:
        try:
            if not Notify.is_initted():
                Notify.init(_APP_ID)
            n = Notify.Notification.new(title, message)
            n.show()
        except Exception as e:
            log_message(_LOG_NOTIFICATION_FAILED.format(e, title, message), level=logging.INFO)
    else:
        log_message(_LOG_NOTIFICATION.format(title, message), level=logging.INFO)


def main():
    if not APPINDICATOR_AVAILABLE:
        print(_ERR_TRAY_DEPS, file=sys.stderr)
        sys.exit(1)
    run_tray_appindicator()


if __name__ == "__main__":
    main()
