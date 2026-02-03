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
        self.icon_index = 0
        self.status_window_gtk = None


def get_tray_state():
    """Return current tray state or None if not set."""
    return _tray_state_ref[0]


def set_tray_state(state):
    """Set current tray state (called from run_tray_appindicator)."""
    _tray_state_ref[0] = state


# Minimum time (seconds) to show syncing icon so quick syncs still give visible feedback
MIN_SYNC_FEEDBACK_SECONDS = 2.0


class Colors:
    YELLOW = (255, 235, 59)
    GREEN = (76, 175, 80)
    BLUE = (33, 150, 243)
    GRAY = (158, 158, 158)
    PURPLE = (156, 39, 176)
    RED = (244, 67, 54)
    AMBER = (255, 193, 7)


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
            if not isinstance(status, dict):
                return
            if status.get(sp.CURRENTLY_SYNCING):
                self.sync_feedback_until = max(self.sync_feedback_until, now + MIN_SYNC_FEEDBACK_SECONDS)
            sync_jobs = status.get(sp.SYNC_JOBS)
            if isinstance(sync_jobs, dict):
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
            if status is not None and not isinstance(status, dict):
                self.daemon_start_error = f"Unexpected status type: {type(status)}"
            elif isinstance(status, dict) and status.get(sp.STATUS) == "error":
                self.daemon_start_error = status.get(sp.MESSAGE, "Unknown error occurred")
        return state

    def get_menu_spec(self, status):
        """Return a list of menu spec dicts (type, label, callback, enabled, submenu) for any backend."""
        current_state = self.get_current_state(status)
        spec = []

        if current_state == DaemonState.INITIAL:
            spec.append({"type": "item", "label": "Initializing...", "callback": None, "enabled": False})
        elif current_state == DaemonState.FAILED:
            spec.extend(self._get_failed_spec(status))
        elif current_state == DaemonState.LIMBO:
            spec.extend(self._get_limbo_spec(status))
        else:
            spec.extend(self._get_normal_spec(status))

        edit_config_enabled = current_state in [DaemonState.RUNNING, DaemonState.SYNCING, DaemonState.CONFIG_INVALID, DaemonState.CONFIG_CHANGED, DaemonState.LIMBO, DaemonState.SYNC_ISSUES]
        spec.extend([
            {"type": "separator"},
            {"type": "item", "label": "Config & Logs", "callback": None, "enabled": True, "submenu": [
                {"type": "item", "label": "Reload Config", "callback": reload_config, "enabled": current_state not in [DaemonState.INITIAL, DaemonState.SHUTTING_DOWN]},
                {"type": "item", "label": "Edit Configuration (experimental)", "callback": edit_config, "enabled": edit_config_enabled},
                {"type": "item", "label": "Open Config Folder", "callback": open_config_file, "enabled": True},
                {"type": "item", "label": "Open Log Folder", "callback": open_log_folder, "enabled": True},
            ]},
            {"type": "separator"},
        ])
        spec.append({"type": "item", "label": "Show Status Window", "callback": show_status_window, "enabled": current_state != DaemonState.INITIAL})
        spec.append({"type": "separator"})

        if status is None:
            spec.append({"type": "item", "label": "Start Daemon", "callback": start_daemon, "enabled": True})
        elif current_state == DaemonState.SHUTTING_DOWN:
            spec.append({"type": "item", "label": "Daemon is down...", "callback": None, "enabled": False})
        else:
            spec.append({"type": "item", "label": "Stop Daemon", "callback": stop_daemon, "enabled": True})

        spec.append({"type": "item", "label": "Exit Tray", "callback": exit_tray, "enabled": True})
        return spec

    def _get_failed_spec(self, status):
        items = [{"type": "item", "label": "⚠️ Daemon is not running", "callback": None, "enabled": False}]
        status_dict = status if isinstance(status, dict) else {}
        error_message = status_dict.get(sp.ERROR) or self.daemon_start_error or "Unknown error"
        first_line = str(error_message).split(chr(10))[0][:80]
        items.append({"type": "item", "label": f"Error: {first_line}", "callback": None, "enabled": False})
        err_msg = status_dict.get(sp.ERROR)
        if self.daemon_start_error or err_msg:
            items.append({"type": "item", "label": "Show Full Error", "callback": lambda *a: show_text_window("Daemon Error Log", self.daemon_start_error or err_msg or "Unknown error"), "enabled": True})
        return items

    def _get_limbo_spec(self, status):
        items = [{"type": "item", "label": "⚠️ Daemon is in limbo state", "callback": None, "enabled": False}]
        if isinstance(status, dict):
            if status.get(sp.CONFIG_INVALID, False):
                items.append({"type": "item", "label": "⚠️ Config is invalid", "callback": None, "enabled": False})
                items.append({"type": "item", "label": f"Error: {(status.get(sp.CONFIG_ERROR_MESSAGE) or 'Unknown error')[:30]}...", "callback": None, "enabled": False})
            if status.get(sp.CONFIG_CHANGED_ON_DISK, False):
                items.append({"type": "item", "label": "⚠️ Config changed on disk", "callback": None, "enabled": False})
        return items

    def _get_normal_spec(self, status):
        items = []
        if not isinstance(status, dict):
            return items
        if _has_sync_issues(status):
            items.append({"type": "item", "label": "⚠ Sync issues detected", "callback": None, "enabled": False})
        if status.get(sp.CONFIG_CHANGED_ON_DISK):
            items.append({"type": "item", "label": "⚠️ Config changed on disk", "callback": None, "enabled": False})
        if _has_sync_issues(status) or status.get(sp.CONFIG_CHANGED_ON_DISK):
            items.append({"type": "separator"})
        currently_syncing = status.get(sp.CURRENTLY_SYNCING)
        if currently_syncing:
            items.append({"type": "item", "label": "Currently syncing:", "callback": None, "enabled": False})
            if isinstance(currently_syncing, str):
                items.append({"type": "item", "label": f"  {str(currently_syncing).strip()}", "callback": None, "enabled": False})
            elif isinstance(currently_syncing, list):
                for job in currently_syncing:
                    items.append({"type": "item", "label": f"  {str(job).strip()}", "callback": None, "enabled": False})
        queued_jobs = status.get(sp.QUEUED_PATHS, [])
        if not isinstance(queued_jobs, (list, tuple)):
            queued_jobs = []
        if queued_jobs:
            items.append({"type": "item", "label": "Queued jobs:", "callback": None, "enabled": False})
            for job in queued_jobs:
                items.append({"type": "item", "label": f"  {job}", "callback": None, "enabled": False})
        sync_jobs = (status.get(sp.SYNC_JOBS) or {}) if isinstance(status.get(sp.SYNC_JOBS), dict) else {}
        if sync_jobs:
            jobs_submenu = []
            for job_key, job_status in sync_jobs.items():
                job_submenu = [
                    {"type": "item", "label": "⚡ Sync Now", "callback": create_sync_now_handler(job_key), "enabled": True},
                    {"type": "item", "label": "⚡ Force Sync Now", "callback": create_sync_now_handler(job_key, force_bisync=True), "enabled": True},
                    {"type": "item", "label": "⚡ Resync + Sync Now", "callback": create_sync_now_handler(job_key, resync=True), "enabled": True},
                    {"type": "item", "label": f"Last sync: {job_status.get(sp.LAST_SYNC) or 'Never'}", "callback": None, "enabled": False},
                    {"type": "item", "label": f"Next run: {job_status.get(sp.NEXT_RUN) or 'Not scheduled'}", "callback": None, "enabled": False},
                    {"type": "item", "label": f"Sync status: {job_status.get(sp.SYNC_STATUS, 'N/A')}", "callback": None, "enabled": False},
                    {"type": "item", "label": f"Resync status: {job_status.get(sp.RESYNC_STATUS, 'N/A')}", "callback": None, "enabled": False},
                ]
                jobs_submenu.append({"type": "item", "label": job_key, "callback": None, "enabled": True, "submenu": job_submenu})
            items.append({"type": "item", "label": "Sync Jobs", "callback": None, "enabled": True, "submenu": jobs_submenu})
        else:
            items.append({"type": "item", "label": "Sync Jobs", "callback": None, "enabled": False})
        return items


    def _icon_color_for_state(self, state):
        """Map DaemonState to tray icon color.
        Intended behavior:
          GREEN  = RUNNING (daemon ok, no sync, no issues)
          BLUE   = SYNCING (sync in progress or just finished successfully for min duration)
          RED    = SYNC_ISSUES (sync failed), CONFIG_INVALID, FAILED (daemon not running / error)
          AMBER  = CONFIG_CHANGED (config changed on disk)
          PURPLE = SHUTTING_DOWN, LIMBO
          GRAY   = OFFLINE (cannot reach daemon)
          YELLOW = INITIAL, STARTING
        """
        if state == DaemonState.INITIAL:
            return Colors.YELLOW
        elif state == DaemonState.STARTING:
            return Colors.YELLOW
        elif state == DaemonState.RUNNING:
            return Colors.GREEN
        elif state == DaemonState.SYNCING:
            return Colors.BLUE
        elif state == DaemonState.SHUTTING_DOWN:
            return Colors.PURPLE
        elif state == DaemonState.SYNC_ISSUES:
            return Colors.RED
        elif state == DaemonState.CONFIG_INVALID:
            return Colors.RED
        elif state == DaemonState.CONFIG_CHANGED:
            return Colors.AMBER
        elif state == DaemonState.LIMBO:
            return Colors.PURPLE
        elif state == DaemonState.OFFLINE:
            return Colors.GRAY
        elif state == DaemonState.FAILED:
            return Colors.RED
        else:
            return Colors.GRAY


def _build_gtk_menu(spec):
    """Build Gtk.Menu from menu spec list (used by AppIndicator backend)."""
    if not APPINDICATOR_AVAILABLE:
        return None
    if spec is None or not isinstance(spec, (list, tuple)):
        spec = []
    menu = Gtk.Menu()
    for s in spec:
        if not isinstance(s, dict):
            continue
        item_type = s.get("type")
        if item_type == "separator":
            menu.append(Gtk.SeparatorMenuItem())
        elif item_type == "item":
            label = s.get("label", "")
            item = Gtk.MenuItem.new_with_label(str(label))
            item.set_sensitive(s.get("enabled", True))
            if s.get("submenu"):
                sub = _build_gtk_menu(s["submenu"])
                item.set_submenu(sub)
            elif s.get("callback"):
                cb = s["callback"]
                item.connect("activate", lambda w, c=cb: c(w) if c else None)
            menu.append(item)
    menu.show_all()
    return menu


def get_daemon_status():
    state = get_tray_state()
    if state is None:
        return None
    try:
        status = request_status(timeout=8, retries=2, retry_delay=0.3)
        if status is None:
            return None
        with state.last_status_lock:
            changed = status != state.last_status
            state.last_status = status
            if changed:
                log_message("Daemon status changed", level=logging.INFO)
                try:
                    log_message(f"New status: {json.dumps(status, default=str)[:100]}...", level=logging.DEBUG)
                except (TypeError, ValueError):
                    log_message("New status: (unable to serialize for debug)", level=logging.DEBUG)
        return status
    except Exception as e:
        log_message(f"Error communicating with daemon: {
                    str(e)}", level=logging.ERROR)
        return None


def create_sync_now_handler(job_key, force_bisync=False, resync=False):
    """Return a menu callback that accepts (widget) from GTK activate signal."""
    def handler(widget=None):
        success = add_to_sync_queue(job_key, force_bisync, resync)
        if not success:
            show_notification("Sync Error", f"Failed to add sync job '{
                              job_key}' to queue. Check the logs for more information.")
    return handler


def stop_daemon(widget=None):
    def _wait_then_refresh():
        for _ in range(6):
            time.sleep(2)
            if request_status(timeout=2) is None:
                break
        GLib.idle_add(update_menu_and_icon)

    try:
        result = request_stop(timeout=5, retries=2, retry_delay=0.3)
        if isinstance(result, dict) and result.get("status") == "success":
            log_message(
                "Daemon is shutting down. Use 'daemon status' to check progress.")
            show_notification("Daemon is shutting down", "The daemon will stop shortly.")
            Thread(target=_wait_then_refresh, daemon=True).start()
        else:
            msg = result.get("message", "Daemon may still be running.") if isinstance(result, dict) else (str(result) if result is not None else "Unknown error")
            log_message(f"Failed to stop daemon: {msg}", level=logging.ERROR)
            show_notification("Stop failed", msg)
            update_menu_and_icon()
    except Exception as e:
        msg = str(e)
        log_message(f"Failed to stop daemon: {msg}", level=logging.ERROR)
        show_notification("Stop failed", msg)
        update_menu_and_icon()


def start_daemon(widget=None):
    state = get_tray_state()
    if state is None or state.daemon_manager is None:
        log_message("Daemon manager not available", level=logging.ERROR)
        return
    dm = state.daemon_manager
    log_message("Starting daemon", level=logging.DEBUG)
    # First, check if the daemon is already running
    current_status = get_daemon_status()
    if current_status is not None:
        log_message("Daemon is already running", level=logging.INFO)
        show_notification("Daemon already running", "The daemon is already running.")
        state.update_queue.put(True)
        return

    cleared = clear_crash_log()
    if cleared:
        log_message("Cleared existing crash log", level=logging.INFO)
    dm.daemon_start_error = None

    try:
        log_message("Attempting to start daemon", level=logging.DEBUG)
        command = ["rclone-bisync-manager", "daemon", "start"]
        if getattr(state.args, "config", None):
            command.extend(["--config", state.args.config])
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Wait for a short time to check for immediate errors
        try:
            stdout, stderr = process.communicate(timeout=2)
            if process.returncode is not None:
                if process.returncode != 0:
                    raise subprocess.CalledProcessError(
                        process.returncode, process.args, stdout, stderr)
                else:
                    log_message("Daemon started successfully",
                                level=logging.INFO)
            else:
                log_message(
                    "Daemon process started, waiting for it to initialize...", level=logging.INFO)
        except subprocess.TimeoutExpired:
            # Process is still running, which is expected
            log_message(
                "Daemon process started, waiting for it to initialize...", level=logging.INFO)
        state.update_queue.put(True)

    except subprocess.CalledProcessError as e:
        error_message = f"Error starting daemon: return code {e.returncode}\nstdout: {e.stdout}\nstderr: {e.stderr}"
        log_message(error_message, level=logging.ERROR)
        dm.daemon_start_error = error_message
        show_notification("Daemon failed to start", (e.stderr or e.stdout or str(e))[:200] or f"Exit code {e.returncode}")
        state.update_queue.put(True)
    except Exception as e:
        error_message = f"Unexpected error starting daemon: {e}\n{traceback.format_exc()}"
        log_message(error_message, level=logging.ERROR)
        dm.daemon_start_error = error_message
        show_notification("Daemon failed to start", str(e)[:200])
        state.update_queue.put(True)


def reload_config(widget=None):
    """Reload daemon config. Accepts optional widget arg from GTK menu activate signal."""
    state = get_tray_state()
    if state is None:
        return False
    try:
        response_data = request_reload()
        if response_data is None:
            log_message("Error reloading configuration: daemon not running", level=logging.ERROR)
            show_notification("Config reload failed", "Daemon is not running.")
            state.update_queue.put(True)
            return False
        if not isinstance(response_data, dict):
            log_message("Unexpected reload response from daemon", level=logging.ERROR)
            show_notification("Config reload failed", "Unexpected response from daemon.")
            state.update_queue.put(True)
            return False
        if response_data.get(sp.STATUS) == "success":
            log_message("Configuration reloaded successfully")
            show_notification("Config reloaded", "Configuration was reloaded successfully.")
        else:
            msg = response_data.get(sp.MESSAGE, "Unknown error")
            log_message(f"Error reloading configuration: {msg}", level=logging.ERROR)
            show_notification("Config reload failed", msg[:200] if len(str(msg)) > 200 else msg)
        state.update_queue.put(True)
        return response_data.get(sp.STATUS) == "success"
    except Exception as e:
        log_message(f"Error communicating with daemon: {str(e)}", level=logging.ERROR)
        show_notification("Config reload failed", str(e)[:200])
        state.update_queue.put(True)
        return False


def add_to_sync_queue(job_key, force_bisync=False, resync=False):
    state = get_tray_state()
    if state is None:
        return False
    try:
        response = request_add_sync(job_key, force_bisync=force_bisync, resync=resync)
        log_message(f"Add to sync queue response: {response}", level=logging.INFO)
        state.update_queue.put(True)
        if response == "OK":
            show_notification("Sync queued", f"Job '{job_key}' was added to the sync queue.")
            return True
        return False
    except Exception as e:
        log_message(f"Error adding job to sync queue: {str(e)}", level=logging.ERROR)
        state.update_queue.put(True)
        return False


def _normalize_icon_color_and_thickness(color, thickness):
    """Return (hex_color_str, int_thickness) for SVG icon rendering."""
    if isinstance(color, tuple) and len(color) >= 3:
        hex_color = '#{:02x}{:02x}{:02x}'.format(color[0], color[1], color[2])
    else:
        hex_color = '#9e9e9e'
    thick = int(thickness) if thickness is not None else 40
    return hex_color, thick


def create_status_image_style1(color, thickness):
    size = 64
    color, thickness = _normalize_icon_color_and_thickness(color, thickness)

    svg_code = '''
    <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
    <path d="M505.6 57.6a20.906667 20.906667 0 0 1 6.4 15.36V170.666667a341.333333 341.333333 0 0 1 295.253333 512 22.186667 22.186667 0 0 1-15.786666 10.24 21.333333 21.333333 0 0 1-17.92-5.973334l-31.146667-31.146666a21.333333 21.333333 0 0 1-3.84-25.173334A253.44 253.44 0 0 0 768 512a256 256 0 0 0-256-256v100.693333a20.906667 20.906667 0 0 1-6.4 15.36l-8.533333 8.533334a21.333333 21.333333 0 0 1-30.293334 0L315.733333 229.973333a21.76 21.76 0 0 1 0-30.293333l151.04-150.613333a21.333333 21.333333 0 0 1 30.293334 0z m51.626667 585.813333a21.333333 21.333333 0 0 0-30.293334 0l-8.533333 8.533334a20.906667 20.906667 0 0 0-6.4 15.36V768a256 256 0 0 1-256-256 248.746667 248.746667 0 0 1 29.866667-119.04 21.76 21.76 0 0 0-3.84-25.173333l-31.573334-31.573334a21.333333 21.333333 0 0 0-17.92-5.973333 22.186667 22.186667 0 0 0-15.786666 11.093333A341.333333 341.333333 0 0 0 512 853.333333v97.706667a20.906667 20.906667 0 0 0 6.4 15.36l8.533333 8.533333a21.333333 21.333333 0 0 0 30.293334 0l151.04-150.613333a21.76 21.76 0 0 0 0-30.293333z" 
    fill="{color}" stroke="{color}" stroke-width="{thickness}" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>
    '''

    svg_code = svg_code.format(color=color, thickness=thickness)
    png_data = svg2png(bytestring=svg_code,
                       output_width=size, output_height=size)
    image = Image.open(BytesIO(png_data)).convert('RGBA')

    return image


def create_status_image_style2(color, thickness):
    size = 64
    color, thickness = _normalize_icon_color_and_thickness(color, thickness)

    svg_code = '''
    <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
    <path d="M917.333 394.667H106.667a32 32 0 0 1 0-64h810.666a32 32 0 0 1 0 64z m0 298.666H106.667a32 32 0 0 1 0-64h810.666a32 32 0 0 1 0 64z" fill="none" stroke="{color}" stroke-width="{thickness}" stroke-linecap="round"/>
    <path d="M106.667 394.667a32 32 0 0 1-22.614-54.614l241.28-241.28A32 32 0 0 1 370.56 144L129.28 385.28a32 32 0 0 1-22.613 9.387z m569.386 539.946A32 32 0 0 1 653.44 880l241.28-241.28a32 32 0 1 1 45.227 45.227l-241.28 241.28a32 32 0 0 1-22.614 9.386z" fill="none" stroke="{color}" stroke-width="{thickness}" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    '''

    svg_code = svg_code.format(color=color, thickness=thickness)
    png_data = svg2png(bytestring=svg_code,
                       output_width=size, output_height=size)
    image = Image.open(BytesIO(png_data)).convert('RGBA')

    return image


def create_status_image(color, style=1, thickness=40):
    if style == 2:
        return create_status_image_style2(color, thickness)
    return create_status_image_style1(color, thickness)


def _show_status_window_gtk():
    """GTK status window (AppIndicator path only)."""
    state = get_tray_state()
    if not APPINDICATOR_AVAILABLE or state is None or state.daemon_manager is None:
        return
    if state.status_window_gtk is not None and state.status_window_gtk.get_visible():
        state.status_window_gtk.present()
        return
    status = get_daemon_status()
    if status is not None and not isinstance(status, dict):
        status = {}
    current_state = state.daemon_manager.get_current_state(status)

    state_title = {
        DaemonState.RUNNING: "Running",
        DaemonState.SYNCING: "Syncing",
        DaemonState.LIMBO: "Limbo",
        DaemonState.INITIAL: "Initializing",
        DaemonState.CONFIG_CHANGED: "Config changed",
        DaemonState.CONFIG_INVALID: "Config invalid",
        DaemonState.SYNC_ISSUES: "Sync issues",
        DaemonState.SHUTTING_DOWN: "Shutting down",
        DaemonState.OFFLINE: "Offline",
        DaemonState.FAILED: "Not running",
    }.get(current_state, "Status")
    win = Gtk.Window(title=f"RClone BiSync Manager – {state_title}")
    win.set_default_size(500, 380)
    state.status_window_gtk = win

    def _on_status_win_destroy(w):
        s = get_tray_state()
        if s is not None:
            s.status_window_gtk = None

    win.connect("destroy", _on_status_win_destroy)

    def _tray_version():
        try:
            from importlib.metadata import version
            return version("rclone-bisync-manager")
        except Exception:
            return "unknown"

    if current_state in [DaemonState.OFFLINE, DaemonState.FAILED]:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        win.add(box)
        box.pack_start(Gtk.Label(label=f"Version: {_tray_version()}", xalign=0), False, False, 0)
        lbl = Gtk.Label(label="⚠ Daemon is not running")
        lbl.get_style_context().add_class("error")
        lbl.set_xalign(0)
        box.pack_start(lbl, False, False, 0)
        if state.daemon_manager.daemon_start_error:
            sw = Gtk.ScrolledWindow()
            sw.set_min_content_height(120)
            tv = Gtk.TextView()
            tv.set_editable(False)
            tv.get_buffer().set_text(str(state.daemon_manager.daemon_start_error or ""))
            sw.add(tv)
            box.pack_start(sw, True, True, 0)
        btn_box = Gtk.Box(spacing=8)
        btn = Gtk.Button(label="Start Daemon")
        def _on_start_clicked(b):
            start_daemon()
            lbl.set_label("Starting daemon… The tray icon will update when ready.")
            b.set_sensitive(False)
        btn.connect("clicked", _on_start_clicked)
        btn_box.pack_start(btn, False, False, 0)
        btn_refresh = Gtk.Button(label="Refresh")
        btn_refresh.connect("clicked", lambda b: (win.destroy(), GLib.idle_add(_show_status_window_gtk)))
        btn_box.pack_start(btn_refresh, False, False, 0)
        box.pack_start(btn_box, False, False, 0)
    else:
        status = status if isinstance(status, dict) else {}
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_margin_top(10)
        outer.set_margin_bottom(10)
        outer.set_margin_start(10)
        outer.set_margin_end(10)
        win.add(outer)
        nb = Gtk.Notebook()
        outer.pack_start(nb, True, True, 0)
        btn_refresh = Gtk.Button(label="Refresh")
        btn_refresh.connect("clicked", lambda b: (win.destroy(), GLib.idle_add(_show_status_window_gtk)))
        outer.pack_start(btn_refresh, False, False, 0)
        outer.pack_start(Gtk.Label(label="Click Refresh to load latest status.", xalign=0), False, False, 0)
        # General
        gen_sw = Gtk.ScrolledWindow()
        gen_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        gen_sw.add(gen_box)
        nb.append_page(gen_sw, Gtk.Label(label="General"))
        status_text = "Daemon is running"
        if current_state == DaemonState.LIMBO:
            status_text = "⚠ Daemon is in limbo state"
        elif current_state == DaemonState.INITIAL:
            status_text = "Daemon is initializing..."
        elif current_state == DaemonState.SYNCING:
            status_text = "Syncing"
        elif current_state == DaemonState.CONFIG_CHANGED:
            status_text = "⚠ Config changed on disk (reload from tray menu)"
        elif current_state == DaemonState.CONFIG_INVALID:
            status_text = "⚠ Config invalid"
        elif current_state == DaemonState.SYNC_ISSUES:
            status_text = "⚠ Sync issues detected"
        gen_box.pack_start(Gtk.Label(label=status_text, xalign=0), False, False, 0)
        version_val = status.get(sp.VERSION) or _tray_version()
        gen_box.pack_start(Gtk.Label(label=f"Version: {version_val}", xalign=0), False, False, 0)
        pid_val = status.get(sp.PID)
        if pid_val is not None:
            gen_box.pack_start(Gtk.Label(label=f"PID: {pid_val}", xalign=0), False, False, 0)
        gen_box.pack_start(Gtk.Label(label=f"Config: {'Valid' if not status.get(sp.CONFIG_INVALID, False) else 'Invalid'}", xalign=0), False, False, 0)
        gen_box.pack_start(Gtk.Label(label=f"Config changed on disk: {'Yes' if status.get(sp.CONFIG_CHANGED_ON_DISK, False) else 'No'}", xalign=0), False, False, 0)
        cfg_path = status.get(sp.CONFIG_FILE_LOCATION)
        if cfg_path:
            gen_box.pack_start(Gtk.Label(label=f"Config file: {cfg_path}", xalign=0), False, False, 0)
        log_path = status.get(sp.LOG_FILE_LOCATION)
        if log_path:
            gen_box.pack_start(Gtk.Label(label=f"Log file: {log_path}", xalign=0), False, False, 0)
        gen_box.pack_start(Gtk.Label(label="Currently syncing:", xalign=0), False, False, 0)
        gen_box.pack_start(Gtk.Label(label=str(status.get(sp.CURRENTLY_SYNCING, "None")), xalign=0), False, False, 0)
        gen_box.pack_start(Gtk.Label(label="Queued jobs:", xalign=0), False, False, 0)
        _queued = status.get(sp.QUEUED_PATHS, []) or []
        if not isinstance(_queued, (list, tuple)):
            _queued = []
        for j in _queued:
            gen_box.pack_start(Gtk.Label(label=f"  {j}", xalign=0), False, False, 0)
        if not _queued:
            gen_box.pack_start(Gtk.Label(label="None", xalign=0), False, False, 0)
        # Sync Jobs
        jobs_sw = Gtk.ScrolledWindow()
        jobs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        jobs_sw.add(jobs_box)
        nb.append_page(jobs_sw, Gtk.Label(label="Sync Jobs"))
        _sync_jobs = status.get(sp.SYNC_JOBS)
        sync_jobs_dict = _sync_jobs if isinstance(_sync_jobs, dict) else {}
        if sync_jobs_dict:
            for job_key, job_status in sync_jobs_dict.items():
                fr = Gtk.Frame(label=str(job_key))
                fr_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                fr.add(fr_box)
                fr_box.pack_start(Gtk.Label(label=f"Last sync: {job_status.get(sp.LAST_SYNC, 'N/A')}", xalign=0), False, False, 0)
                fr_box.pack_start(Gtk.Label(label=f"Next run: {job_status.get(sp.NEXT_RUN, 'N/A')}", xalign=0), False, False, 0)
                fr_box.pack_start(Gtk.Label(label=f"Sync status: {job_status.get(sp.SYNC_STATUS, 'N/A')}", xalign=0), False, False, 0)
                fr_box.pack_start(Gtk.Label(label=f"Resync status: {job_status.get(sp.RESYNC_STATUS, 'N/A')}", xalign=0), False, False, 0)
                jobs_box.pack_start(fr, False, False, 0)
        else:
            jobs_box.pack_start(Gtk.Label(label="No sync jobs configured.", xalign=0), False, False, 0)
        # Sync Errors
        err_sw = Gtk.ScrolledWindow()
        err_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        err_sw.add(err_box)
        nb.append_page(err_sw, Gtk.Label(label="Sync Errors"))
        sync_errors = status.get(sp.SYNC_ERRORS) if isinstance(status.get(sp.SYNC_ERRORS), dict) else {}
        if sync_errors:
            for path, err in sync_errors.items():
                fr = Gtk.Frame(label=str(path))
                fr_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                fr.add(fr_box)
                err_dict = err if isinstance(err, dict) else {}
                for k, v in err_dict.items():
                    fr_box.pack_start(Gtk.Label(label=f"{k}: {v}", xalign=0), False, False, 0)
                err_box.pack_start(fr, False, False, 0)
        else:
            err_box.pack_start(Gtk.Label(label="No sync errors at this time.", xalign=0), False, False, 0)
        # Config
        cfg_sw = Gtk.ScrolledWindow()
        cfg_tv = Gtk.TextView()
        cfg_tv.set_editable(False)
        cfg_sw.add(cfg_tv)
        nb.append_page(cfg_sw, Gtk.Label(label="Config"))
        cfg_path = status.get(sp.CONFIG_FILE_LOCATION)
        if cfg_path and os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8", errors="replace") as f:
                cfg_tv.get_buffer().set_text(f.read())
        else:
            cfg_tv.get_buffer().set_text("Config file not found or inaccessible.")
    win.show_all()


def show_status_window(widget=None):
    _show_status_window_gtk()


def open_config_file(widget=None):
    config_file_path = get_config_file_path()
    if config_file_path:
        config_dir = os.path.dirname(config_file_path)
        if os.name == 'nt':  # For Windows
            os.startfile(config_dir)
        elif os.name == 'posix':  # For macOS and Linux
            subprocess.call(('xdg-open', config_dir))
    else:
        log_message("Config file path not found", level=logging.ERROR)
        show_notification("Config folder", "Path not available. Is the daemon running?")


def open_log_folder(widget=None):
    log_file_path = get_log_file_path()
    if log_file_path:
        log_dir = os.path.dirname(log_file_path)
        if log_dir:  # only open dir when path has a directory component
            if os.name == 'nt':  # For Windows
                os.startfile(log_dir)
            elif os.name == 'posix':  # For macOS and Linux
                subprocess.call(('xdg-open', log_dir))
        else:
            log_message("Log path has no directory (e.g. plain filename); cannot open folder.", level=logging.INFO)
            show_notification("Log folder", "Log path has no directory component.")
    else:
        log_message("Log file path not found", level=logging.ERROR)
        show_notification("Log folder", "Path not available. Is the daemon running?")


def _get_status_path(key):
    """Return status[key] from fresh daemon status, or None if unavailable."""
    status = get_daemon_status()
    return status.get(key) if isinstance(status, dict) else None


def get_config_file_path():
    return _get_status_path(sp.CONFIG_FILE_LOCATION)


def get_log_file_path():
    return _get_status_path(sp.LOG_FILE_LOCATION)


def _show_text_window_gtk(title, content):
    """GTK text window (AppIndicator path only)."""
    if not APPINDICATOR_AVAILABLE:
        return
    win = Gtk.Window(title=str(title) if title is not None else "")
    win.set_default_size(600, 400)
    sw = Gtk.ScrolledWindow()
    tv = Gtk.TextView()
    tv.set_editable(False)
    tv.set_wrap_mode(Gtk.WrapMode.WORD)
    tv.get_buffer().set_text(str(content) if content is not None else "")
    sw.add(tv)
    win.add(sw)
    win.show_all()


def show_text_window(title, content):
    _show_text_window_gtk(title, content)


def _write_tray_icon_to_path(path, display_state):
    """Write status image to path (for AppIndicator). display_state is derived at paint time from fresh status."""
    tray_state = get_tray_state()
    if tray_state is None or tray_state.daemon_manager is None or tray_state.args is None:
        return
    try:
        color = tray_state.daemon_manager._icon_color_for_state(display_state)
        img = create_status_image(color, style=tray_state.args.icon_style, thickness=tray_state.args.icon_thickness)
        img.save(path, "PNG")
    except Exception as e:
        log_message(f"Error writing tray icon: {e}", level=logging.ERROR)


def _update_appindicator_ui():
    """Rebuild indicator menu and icon (run on main thread via GLib.idle_add).
    Fetches status once; derives icon state at paint time so icon cannot be stale.
    """
    state = get_tray_state()
    try:
        if state is None or state.indicator is None or not state.icon_paths:
            return False
        if state.daemon_manager is None:
            return False
        status = get_daemon_status()
        if status is not None:
            state.daemon_manager.update_sync_feedback(status)
        display_state = state.daemon_manager.get_effective_state_for_display(status)
        path = state.icon_paths[state.icon_index]
        _write_tray_icon_to_path(path, display_state)
        state.indicator.set_icon(path)
        state.icon_index = 1 - state.icon_index
        spec = state.daemon_manager.get_menu_spec(status)
        menu = _build_gtk_menu(spec)
        if menu is not None:
            state.indicator.set_menu(menu)
    except Exception as e:
        log_message(f"Error updating tray UI: {e}", level=logging.ERROR)
        log_message(traceback.format_exc(), level=logging.DEBUG)
    return False  # GLib.idle_add: return False to remove source


def run_tray_appindicator():
    """Run tray using AppIndicator3 (SNI) + GTK (notifications, status window, config editor)."""
    state = TrayState()
    state.daemon_manager = DaemonManager()
    parser = argparse.ArgumentParser()
    parser.add_argument("--icon-style", type=int, choices=[1, 2], default=1)
    parser.add_argument("--icon-thickness", type=int, default=40)
    parser.add_argument("--log-level", type=str, choices=["NONE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], default="NONE")
    parser.add_argument("--enable-experimental", action="store_true")
    parser.add_argument("--config", type=str)
    state.args = parser.parse_args()
    state.update_queue = Queue()
    state.last_status = None
    state.last_status_lock = Lock()
    state.offline_miss_count = 0
    state.indicator = None
    state.icon_paths = None
    state.icon_index = 0
    state.status_window_gtk = None
    set_tray_state(state)

    minimal = type("TrayLogConfig", (), {})()
    minimal.console_log = state.args.log_level != "NONE"
    minimal.log_file_path = None
    minimal.min_console_level = getattr(logging, state.args.log_level) if state.args.log_level != "NONE" else (logging.CRITICAL + 1)
    set_config(minimal)
    setup_loggers(console_log=minimal.console_log)

    cleared = clear_crash_log()
    if cleared:
        log_message("Cleared existing crash log", level=logging.INFO)
    initial_status = get_daemon_status()
    if initial_status is not None:
        state.daemon_manager.update_sync_feedback(initial_status)
    initial_state = state.daemon_manager.get_effective_state_for_display(initial_status)

    tmp = tempfile.gettempdir()
    state.icon_paths = [
        os.path.join(tmp, "rclone-bisync-manager-tray-icon-0.png"),
        os.path.join(tmp, "rclone-bisync-manager-tray-icon-1.png"),
    ]
    state.icon_index = 0
    _write_tray_icon_to_path(state.icon_paths[0], initial_state)
    state.indicator = AppIndicator3.Indicator.new(
        "rclone-bisync-manager",
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
                log_message(f"Error in handle_updates: {e}", level=logging.ERROR)
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
    state = get_tray_state()
    if state is None or state.daemon_manager is None:
        return
    log_message("Updating menu and icon.", level=logging.DEBUG)
    GLib.idle_add(_update_appindicator_ui)


def check_status_and_update():
    last_status = None
    while True:
        try:
            state = get_tray_state()
            if state is None or state.daemon_manager is None:
                time.sleep(1)
                continue
            crash_message = read_crash_log()
            if crash_message:
                crash_message = str(crash_message).strip()
                if state.daemon_manager.daemon_start_error != crash_message:
                    state.daemon_manager.daemon_start_error = crash_message
                    state.update_queue.put(True)
                    log_message("Daemon crashed.", level=logging.ERROR)
                    log_message(f"Crash message: {
                                crash_message}", level=logging.ERROR)
                continue

            current_status = get_daemon_status()
            if current_status is None:
                state.offline_miss_count += 1
            else:
                state.offline_miss_count = 0
                state.daemon_manager.update_sync_feedback(current_status)
            # Clear expired feedback and trigger one more icon update when it expires
            with state.daemon_manager.state_lock:
                if state.daemon_manager.sync_feedback_until > 0 and time.monotonic() >= state.daemon_manager.sync_feedback_until:
                    state.daemon_manager.sync_feedback_until = 0
                    state.update_queue.put(True)

            # Refresh when status changed; skip when holding sticky (first None tick)
            holding_sticky = current_status is None and state.offline_miss_count < 2
            if not holding_sticky and current_status != last_status:
                log_message("Status or state changed. Updating menu and icon.", level=logging.DEBUG)
                log_message(f"New status: {current_status}", level=logging.DEBUG)
                state.update_queue.put(True)

            last_status = current_status

        except Exception as e:
            log_message(f"Error in check_status_and_update: {
                        e}", level=logging.ERROR)
            log_message(f"Error details: {
                        traceback.format_exc()}", level=logging.DEBUG)

        time.sleep(1)


def edit_config(widget=None):
    state = get_tray_state()
    if state is None or state.daemon_manager is None:
        log_message("Daemon manager not available", level=logging.ERROR)
        return
    try:
        config_file = get_config_file_path()
        if not config_file:
            log_message("Config file path not available", level=logging.ERROR)
            dlg = Gtk.MessageDialog(
                transient_for=None, flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Config file path not available",
            )
            dlg.run()
            dlg.destroy()
            return
        from rclone_bisync_manager.config_editor import edit_config_gtk
        edit_config_gtk(config_file)
        reload_config()
    except Exception as e:
        log_message(f"Error editing config: {str(e)}", level=logging.ERROR)
        dlg = Gtk.MessageDialog(
            transient_for=None, flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=f"Failed to edit config: {e}",
        )
        dlg.run()
        dlg.destroy()


def exit_tray(widget=None):
    log_message("Exiting tray application", level=logging.INFO)
    Gtk.main_quit()
    sys.exit(0)


def show_notification(title, message):
    title = str(title) if title is not None else ""
    message = str(message) if message is not None else ""
    if NOTIFY_AVAILABLE:
        try:
            if not Notify.is_initted():
                Notify.init("rclone-bisync-manager")
            n = Notify.Notification.new(title, message)
            n.show()
        except Exception as e:
            log_message(f"Notification failed: {e}; {title} - {message}", level=logging.INFO)
    else:
        log_message(f"Notification: {title} - {message}", level=logging.INFO)


def main():
    if not APPINDICATOR_AVAILABLE:
        print("Tray requires AppIndicator3 + GTK3 + PyGObject. On Arch: libappindicator, gtk3, libnotify, python-gobject.", file=sys.stderr)
        sys.exit(1)
    run_tray_appindicator()


if __name__ == "__main__":
    main()
