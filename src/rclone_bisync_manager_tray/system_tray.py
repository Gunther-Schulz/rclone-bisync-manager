#!/usr/bin/env python3

from tkinter import messagebox, ttk
import tkinter
import pystray
from PIL import Image
import socket
import json
import time
import subprocess
import os
import enum
from dataclasses import dataclass
from io import BytesIO
from cairosvg import svg2png
import argparse
import logging
import traceback
import queue
from queue import Queue
from threading import Thread, Lock
from rclone_bisync_manager_tray.config_editor import edit_config
import sys
from pystray import MenuItem as item
# os.environ['PYSTRAY_BACKEND'] = 'gtk'  # or 'qt'


# Global variables
update_queue = queue.Queue()
icon = None
last_status = None
last_offline_log_time = 0

# Set up logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

global daemon_manager
daemon_manager = None

# At the top of the file, after imports
debug = False
args = None

# Add this global variable at the top of the file
status_window = None


def log_message(message, level=logging.INFO):
    global args, debug
    if args and args.log_level != 'NONE':
        logging.log(level, message)
    elif debug:
        print(message)


class DaemonState(enum.Enum):
    INITIAL = "initial"
    STARTING = "starting"
    RUNNING = "running"
    SYNCING = "syncing"
    SHUTTING_DOWN = "shutting_down"
    SYNC_ISSUES = "sync_issues"
    CONFIG_INVALID = "config_invalid"
    CONFIG_CHANGED = "config_changed"
    LIMBO = "limbo"
    OFFLINE = "offline"
    FAILED = "failed"


@dataclass
class StateInfo:
    color: tuple
    menu_items: list
    icon_text: str


class Colors:
    YELLOW = (255, 235, 59)
    GREEN = (76, 175, 80)
    BLUE = (33, 150, 243)
    GRAY = (158, 158, 158)
    PURPLE = (156, 39, 176)
    ORANGE = (255, 152, 0)
    RED = (244, 67, 54)
    AMBER = (255, 193, 7)


class DaemonManager:
    def __init__(self):
        self.current_state = DaemonState.INITIAL
        self.daemon_start_error = None
        self.state_lock = Lock()

    def update_state(self, new_state):
        with self.state_lock:
            if new_state != self.current_state:
                log_message(f"State changing from {self.current_state} to {
                            new_state}", level=logging.INFO)
                self.current_state = new_state
                return True
        return False

    def get_current_state(self, status):
        if self.daemon_start_error:
            return DaemonState.FAILED
        if status is None:
            return DaemonState.OFFLINE
        elif isinstance(status, dict):
            if status.get('status') == 'error':
                self.daemon_start_error = status.get(
                    'message', 'Unknown error occurred')
                return DaemonState.FAILED
            elif status.get('error'):
                return DaemonState.FAILED
            elif status.get('shutting_down'):
                return DaemonState.SHUTTING_DOWN
            elif status.get('in_limbo'):
                return DaemonState.LIMBO
            elif status.get('config_invalid'):
                return DaemonState.CONFIG_INVALID
            elif self._has_sync_issues(status):
                return DaemonState.SYNC_ISSUES
            elif status.get('config_changed_on_disk'):
                return DaemonState.CONFIG_CHANGED
            elif status.get('currently_syncing'):
                return DaemonState.SYNCING
            elif status.get('running', False):
                return DaemonState.RUNNING
            else:
                return DaemonState.OFFLINE
        else:
            self.daemon_start_error = f"Unexpected status type: {type(status)}"
            return DaemonState.FAILED

    def _has_sync_issues(self, status):
        return (
            any(
                job["sync_status"] not in ["COMPLETED", "NONE", "IN_PROGRESS"] or
                job["resync_status"] not in ["COMPLETED", "NONE", "IN_PROGRESS"] or
                job.get("hash_warnings", False)
                for job in status.get("sync_jobs", {}).values()
            ) or
            bool(status.get("sync_errors"))
        )

    def get_menu_items(self, status):
        current_state = self.get_current_state(status)
        menu_items = []

        if current_state == DaemonState.INITIAL:
            menu_items.append(pystray.MenuItem(
                "Initializing...", None, enabled=False))
        elif current_state == DaemonState.FAILED:
            menu_items.extend(self._get_failed_menu_items(status))
        elif current_state == DaemonState.LIMBO:
            menu_items.extend(self._get_limbo_menu_items(status))
        else:
            menu_items.extend(self._get_normal_menu_items(status))

        menu_items.extend([
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Config & Logs", pystray.Menu(
                pystray.MenuItem("Reload Config", reload_config, enabled=current_state not in [
                    DaemonState.INITIAL, DaemonState.SHUTTING_DOWN]),
                pystray.MenuItem("Open Config Folder", open_config_file),
                pystray.MenuItem("Open Log Folder", open_log_folder)
            )),
            pystray.Menu.SEPARATOR,
        ])

        # Show Status Window menu item (enabled for all states except INITIAL)
        menu_items.append(pystray.MenuItem(
            "Show Status Window", show_status_window, enabled=current_state != DaemonState.INITIAL))
        menu_items.append(pystray.Menu.SEPARATOR)

        # Add Start/Stop Daemon menu item
        daemon_status = get_daemon_status()
        if daemon_status is None:
            menu_items.append(pystray.MenuItem("Start Daemon", start_daemon))
        elif current_state == DaemonState.SHUTTING_DOWN:
            menu_items.append(pystray.MenuItem("Daemon is down...", lambda: None, enabled=False))
        else:
            menu_items.append(pystray.MenuItem("Stop Daemon", stop_daemon))

        # Add experimental features if the flag is set
        if args.enable_experimental:
            if current_state in [DaemonState.RUNNING, DaemonState.CONFIG_INVALID,
                                 DaemonState.CONFIG_CHANGED, DaemonState.LIMBO,
                                 DaemonState.SYNC_ISSUES]:
                menu_items.extend([
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        "Edit Configuration (experimental)", edit_config),
                    # Add other experimental features here in the future
                ])

        menu_items.append(pystray.MenuItem("Exit Tray", exit_tray))
        return menu_items

    def _get_failed_menu_items(self, status):
        items = [pystray.MenuItem(
            "⚠️ Daemon is not running", None, enabled=False)]
        error_message = status.get("error") if status else None
        error_message = error_message or self.daemon_start_error or "Unknown error"
        items.append(pystray.MenuItem(
            f"Error: {error_message.split('\n')[0]}", None, enabled=False))
        if self.daemon_start_error or (status and status.get("error")):
            items.append(pystray.MenuItem("Show Full Error", lambda: show_text_window(
                "Daemon Error Log", self.daemon_start_error or status.get("error"))))
        return items

    def _get_limbo_menu_items(self, status):
        items = [pystray.MenuItem(
            "⚠️ Daemon is in limbo state", None, enabled=False)]
        if status:
            if status.get("config_invalid", False):
                items.append(pystray.MenuItem(
                    "⚠️ Config is invalid", None, enabled=False))
                items.append(pystray.MenuItem(f"Error: {status.get(
                    'config_error_message', 'Unknown error')[:30]}...", None, enabled=False))
            if status.get("config_changed_on_disk", False):
                items.append(pystray.MenuItem(
                    "⚠️ Config changed on disk", None, enabled=False))
        return items

    def _get_normal_menu_items(self, status):
        items = []
        if status:
            if self._has_sync_issues(status):
                items.append(pystray.MenuItem(
                    "⚠ Sync issues detected", None, enabled=False))
            if status.get("config_changed_on_disk"):
                items.append(pystray.MenuItem(
                    "⚠️ Config changed on disk", None, enabled=False))

            if self._has_sync_issues(status) or status.get("config_changed_on_disk"):
                items.append(pystray.Menu.SEPARATOR)

            currently_syncing = status.get('currently_syncing')
            if currently_syncing:
                items.append(pystray.MenuItem(
                    "Currently syncing:", None, enabled=False))
                if isinstance(currently_syncing, str):
                    items.append(pystray.MenuItem(
                        f"  {currently_syncing.strip()}", None, enabled=False))
                elif isinstance(currently_syncing, list):
                    for job in currently_syncing:
                        items.append(pystray.MenuItem(
                            f"  {job.strip()}", None, enabled=False))

            queued_jobs = status.get('queued_paths', [])
            if queued_jobs:
                items.append(pystray.MenuItem(
                    "Queued jobs:", None, enabled=False))
                for job in queued_jobs:
                    items.append(pystray.MenuItem(
                        f"  {job}", None, enabled=False))

            # Add sync jobs submenu
            if "sync_jobs" in status:
                jobs_submenu = []
                for job_key, job_status in status["sync_jobs"].items():
                    job_submenu = pystray.Menu(
                        pystray.MenuItem(
                            "⚡ Sync Now", create_sync_now_handler(job_key)),
                        pystray.MenuItem(
                            "⚡ Force Sync Now", create_sync_now_handler(job_key, force_bisync=True)),
                        pystray.MenuItem(
                            "⚡ Resync + Sync Now", create_sync_now_handler(job_key, resync=True)),
                        pystray.MenuItem(
                            f"Last sync: {job_status['last_sync'] or 'Never'}", None, enabled=False),
                        pystray.MenuItem(
                            f"Next run: {job_status['next_run'] or 'Not scheduled'}", None, enabled=False),
                        pystray.MenuItem(
                            f"Sync status: {job_status['sync_status']}", None, enabled=False),
                        pystray.MenuItem(f"Resync status: {
                                         job_status['resync_status']}", None, enabled=False),
                    )
                    jobs_submenu.append(pystray.MenuItem(job_key, job_submenu))
                items.append(pystray.MenuItem(
                    "Sync Jobs", pystray.Menu(*jobs_submenu)))
            else:
                items.append(pystray.MenuItem(
                    "Sync Jobs", None, enabled=False))

        return items

    def get_icon_color(self, status):
        current_state = self.get_current_state(status)
        if current_state == DaemonState.INITIAL:
            return Colors.YELLOW
        elif current_state == DaemonState.STARTING:
            return Colors.YELLOW
        elif current_state == DaemonState.RUNNING:
            return Colors.GREEN
        elif current_state == DaemonState.SYNCING:
            return Colors.BLUE
        elif current_state == DaemonState.SHUTTING_DOWN:
            return Colors.PURPLE
        elif current_state == DaemonState.SYNC_ISSUES:
            return Colors.RED
        elif current_state == DaemonState.CONFIG_INVALID:
            return Colors.RED
        elif current_state == DaemonState.CONFIG_CHANGED:
            return Colors.AMBER
        elif current_state == DaemonState.LIMBO:
            return Colors.PURPLE
        elif current_state == DaemonState.OFFLINE:
            return Colors.GRAY
        elif current_state == DaemonState.FAILED:
            return Colors.RED
        else:
            return Colors.GRAY

    def get_icon_text(self, status):
        current_state = self.get_current_state(status)
        if current_state == DaemonState.INITIAL:
            return "INIT"
        elif current_state == DaemonState.STARTING:
            return "START"
        elif current_state == DaemonState.SYNCING:
            return "SYNC"
        elif current_state == DaemonState.CONFIG_INVALID:
            return "CFG!"
        elif current_state == DaemonState.CONFIG_CHANGED:
            return "CFG?"
        elif current_state == DaemonState.SYNC_ISSUES:
            return "WARN"
        elif current_state == DaemonState.LIMBO:
            return "LIMBO"
        elif current_state == DaemonState.SHUTTING_DOWN:
            return "STOP"
        elif current_state == DaemonState.FAILED:
            return "FAIL"
        else:
            return "RUN"

    def get_config_file_path(self):
        status = get_daemon_status()
        if status and isinstance(status, dict):
            return status.get('config_file_location')
        return None


def get_daemon_status():
    global last_status, last_offline_log_time
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(5)  # Set a timeout of 5 seconds
        client.connect(socket_path)
        client.sendall(b"STATUS")

        chunks = []
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        response = b''.join(chunks).decode()

        status = json.loads(response)
        client.close()

        if status != last_status:
            log_message("Daemon status changed", level=logging.INFO)
            log_message(f"New status: {json.dumps(status)[
                        :100]}...", level=logging.DEBUG)

        last_status = status
        last_offline_log_time = 0
        return status
    except socket.timeout:
        log_message("Timeout while getting daemon status",
                    level=logging.WARNING)
        return None
    except json.JSONDecodeError as e:
        log_message(f"Error decoding daemon status: {
                    str(e)}", level=logging.ERROR)
        return None
    except Exception as e:
        log_message(f"Error communicating with daemon: {
                    str(e)}", level=logging.ERROR)
        return None


def create_sync_now_handler(job_key, force_bisync=False, resync=False):
    def handler(item):
        success = add_to_sync_queue(job_key, force_bisync, resync)
        if not success:
            show_notification("Sync Error", f"Failed to add sync job '{
                              job_key}' to queue. Check the logs for more information.")
    return handler


def stop_daemon():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(socket_path)
        client.sendall(b"STOP")
        response = client.recv(1024).decode()
        client.close()
        log_message(
            "Daemon is shutting down. Use 'daemon status' to check progress.")

        # Immediately update the menu to show "Shutting Down"
        update_menu_and_icon()
    except Exception as e:
        log_message(f"Error stopping daemon: {e}", level=logging.ERROR)


def start_daemon():
    global daemon_manager
    log_message("Starting daemon", level=logging.DEBUG)
    # First, check if the daemon is already running
    current_status = get_daemon_status()
    if current_status is not None:
        log_message("Daemon is already running", level=logging.INFO)
        daemon_manager.update_state(DaemonState.RUNNING)
        update_queue.put(True)
        return

    daemon_manager.update_state(DaemonState.STARTING)

    clear_crash_log()  # Clear the crash log before starting the daemon
    daemon_manager.daemon_start_error = None

    try:
        log_message("Attempting to start daemon", level=logging.DEBUG)
        command = ["rclone-bisync-manager", "daemon", "start"]
        if args.config:
            command.extend(["--config", args.config])
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

    except subprocess.CalledProcessError as e:
        error_message = f"Error starting daemon: return code {
            e.returncode}\nstdout: {e.stdout}\nstderr: {e.stderr}"
        log_message(error_message, level=logging.ERROR)
        daemon_manager.daemon_start_error = error_message
        daemon_manager.update_state(DaemonState.FAILED)
        update_queue.put(True)
    except Exception as e:
        error_message = f"Unexpected error starting daemon: {
            e}\n{traceback.format_exc()}"
        log_message(error_message, level=logging.ERROR)
        daemon_manager.daemon_start_error = error_message
        daemon_manager.update_state(DaemonState.FAILED)
        update_queue.put(True)


def reload_config():
    global daemon_manager, icon
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(socket_path)
        client.sendall(b"RELOAD")
        response = client.recv(1024).decode()
        client.close()

        try:
            response_data = json.loads(response)
            if response_data["status"] == "success":
                log_message("Configuration reloaded successfully")
            else:
                log_message(f"Error reloading configuration: {
                            response_data['message']}", level=logging.ERROR)

            current_status = get_daemon_status()
            new_menu = pystray.Menu(
                *daemon_manager.get_menu_items(current_status))
            new_icon = create_status_image(
                daemon_manager.get_icon_color(current_status),
                daemon_manager.get_icon_text(current_status),
                style=args.icon_style,
                thickness=args.icon_thickness
            )

            icon.menu = new_menu
            icon.icon = new_icon
            icon.update_menu()

            return response_data["status"] == "success"
        except json.JSONDecodeError:
            log_message(f"Error: Invalid JSON response from daemon: {
                        response}", level=logging.ERROR)
            return False
    except Exception as e:
        log_message(f"Error communicating with daemon: {
                    str(e)}", level=logging.ERROR)
        return False


def add_to_sync_queue(job_key, force_bisync=False, resync=False):
    socket_path = '/tmp/rclone_bisync_manager_add_sync.sock'
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(socket_path)
        client.sendall(json.dumps(
            {"job_key": job_key, "force_bisync": force_bisync, "resync": resync}).encode())

        chunks = []
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        response = b''.join(chunks).decode()

        client.close()
        log_message(f"Add to sync queue response: {
                    response}", level=logging.INFO)

        # Trigger an immediate update of the menu and icon
        update_queue.put(True)
        return True
    except Exception as e:
        log_message(f"Error adding job to sync queue: {
                    str(e)}", level=logging.ERROR)
        return False


def determine_arrow_color(color, icon_text):
    if color == (158, 158, 158):  # Gray (error state)
        return "#FFFFFF"  # White for error (daemon not running)
    elif color == (33, 150, 243):  # Blue (syncing)
        return "#FFFFFF"  # White
    elif color == (244, 67, 54):  # Red (config invalid)
        return "#FFFFFF"  # White for invalid config
    elif color == (255, 193, 7):  # Amber (config changed on disk)
        return "#000000"  # Black for config changed on disk
    elif color == (255, 152, 0):  # Orange (sync issues)
        return "#000000"  # Black for sync issues
    else:
        return "#FFFFFF"  # White for normal operation


def create_status_image_style1(color, thickness):
    size = 64

    if isinstance(color, tuple):
        color = '#{:02x}{:02x}{:02x}'.format(color[0], color[1], color[2])

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

    if isinstance(color, tuple):
        color = '#{:02x}{:02x}{:02x}'.format(color[0], color[1], color[2])

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


def create_status_image(color, icon_text, style=1, thickness=40):
    if style == 2:
        return create_status_image_style2(color, thickness)
    else:
        return create_status_image_style1(color, thickness)


def determine_text_color(background_color):
    # Simple logic to determine if text should be black or white based on background brightness
    r, g, b = background_color[:3]
    brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if brightness > 0.5 else "#FFFFFF"


def show_status_window():
    global daemon_manager, status_window

    # Check if the window is already open
    if status_window is not None and status_window.winfo_exists():
        # If it exists, just focus on it
        status_window.lift()
        status_window.focus_force()
        return

    status = get_daemon_status()
    current_state = daemon_manager.get_current_state(status)

    status_window = tkinter.Tk()
    status_window.title("RClone BiSync Manager Status")
    status_window.geometry("400x300")

    style = ttk.Style()
    style.theme_use('clam')

    if current_state in [DaemonState.OFFLINE, DaemonState.FAILED]:
        ttk.Label(status_window, text="⚠️ Daemon is not running",
                  foreground="red", font=("", 14, "bold")).pack(pady=(20, 10))

        if daemon_manager.daemon_start_error:
            error_frame = ttk.LabelFrame(status_window, text="Error Details")
            error_frame.pack(pady=10, padx=10, fill='x')
            error_text = tkinter.Text(
                error_frame, wrap=tkinter.WORD, height=25)
            error_text.pack(pady=5, padx=5, fill='both', expand=True)
            error_text.insert(tkinter.END, daemon_manager.daemon_start_error)
            error_text.config(state=tkinter.DISABLED)

        ttk.Button(status_window, text="Start Daemon", command=lambda: [
                   start_daemon(), status_window.destroy()]).pack(pady=20)
    else:
        notebook = ttk.Notebook(status_window)
        notebook.pack(expand=True, fill='both')

        general_frame = ttk.Frame(notebook)
        notebook.add(general_frame, text='General')

        if current_state == DaemonState.LIMBO:
            status_text = "⚠️ Daemon is in limbo state"
        elif current_state == DaemonState.INITIAL:
            status_text = "Daemon is initializing..."
        elif current_state in [DaemonState.OFFLINE, DaemonState.FAILED]:
            status_text = "⚠️ Daemon is not running"
        else:
            status_text = "Daemon is running"

        status_label = ttk.Label(general_frame, text=status_text,
                                 foreground="red" if current_state in [DaemonState.OFFLINE, DaemonState.FAILED, DaemonState.LIMBO] else "black")
        status_label.pack(pady=(10, 0))

        ttk.Label(general_frame, text=f"Config: {'Valid' if not status.get(
            'config_invalid', False) else 'Invalid'}").pack(pady=5)
        ttk.Label(general_frame, text=f"Config changed on disk: {
                  'Yes' if status.get('config_changed_on_disk', False) else 'No'}").pack(pady=5)

        currently_syncing = status.get('currently_syncing', 'None')
        ttk.Label(general_frame, text="Currently syncing:").pack(
            anchor='w', padx=5, pady=(5, 0))
        ttk.Label(general_frame, text=currently_syncing).pack(
            anchor='w', padx=20, pady=(0, 5))

        queued_jobs = status.get('queued_paths', [])
        ttk.Label(general_frame, text="Queued jobs:").pack(
            anchor='w', padx=5, pady=(5, 0))
        if queued_jobs:
            for job in queued_jobs:
                ttk.Label(general_frame, text=job).pack(
                    anchor='w', padx=20, pady=(0, 2))
        else:
            ttk.Label(general_frame, text="None").pack(
                anchor='w', padx=20, pady=(0, 5))

        jobs_frame = ttk.Frame(notebook)
        notebook.add(jobs_frame, text='Sync Jobs')

        if "sync_jobs" in status:
            for job_key, job_status in status["sync_jobs"].items():
                job_frame = ttk.LabelFrame(jobs_frame, text=job_key)
                job_frame.pack(pady=5, padx=5, fill='x')

                ttk.Label(job_frame, text=f"Last sync: {
                          job_status['last_sync']}").pack(anchor='w')
                ttk.Label(job_frame, text=f"Next run: {
                          job_status['next_run']}").pack(anchor='w')
                ttk.Label(job_frame, text=f"Sync status: {
                          job_status['sync_status']}").pack(anchor='w')
                ttk.Label(job_frame, text=f"Resync status: {
                          job_status['resync_status']}").pack(anchor='w')

        errors_frame = ttk.Frame(notebook)
        notebook.add(errors_frame, text='Sync Errors')

        if status.get("sync_errors"):
            for path, error_info in status["sync_errors"].items():
                error_frame = ttk.LabelFrame(errors_frame, text=path)
                error_frame.pack(pady=5, padx=5, fill='x')

                ttk.Label(error_frame, text=f"Sync Type: {
                          error_info['sync_type']}").pack(anchor='w')
                ttk.Label(error_frame, text=f"Error Code: {
                          error_info['error_code']}").pack(anchor='w')
                ttk.Label(error_frame, text=f"Message: {
                          error_info['message']}").pack(anchor='w')
                ttk.Label(error_frame, text=f"Timestamp: {
                          error_info['timestamp']}").pack(anchor='w')
        else:
            ttk.Label(errors_frame, text="No sync errors at this time.").pack(
                pady=20)

        config_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text='Config')

        config_text = tkinter.Text(config_frame, wrap=tkinter.WORD)
        config_text.pack(pady=10, padx=10, fill='both', expand=True)

        config_file_path = status.get('config_file_location')
        if config_file_path and os.path.exists(config_file_path):
            with open(config_file_path, 'r') as config_file:
                config_message = config_file.read()
        else:
            config_message = "Config file not found or inaccessible."

        config_text.insert(tkinter.END, config_message)
        config_text.config(state=tkinter.DISABLED)

        config_scrollbar = ttk.Scrollbar(
            config_frame, orient="vertical", command=config_text.yview)
        config_scrollbar.pack(side=tkinter.RIGHT, fill=tkinter.Y)
        config_text.configure(yscrollcommand=config_scrollbar.set)

        if current_state == DaemonState.LIMBO:
            error_frame = ttk.Frame(notebook)
            notebook.add(error_frame, text='Config Error Details')

            error_text = tkinter.Text(error_frame, wrap=tkinter.WORD)
            error_text.pack(pady=10, padx=10, fill='both', expand=True)

            error_message = "Daemon is in limbo state. Config error details:\n\n"
            if status.get("config_invalid", False):
                error_message += f"Config is invalid.\nError: {
                    status.get('config_error_message', 'Unknown error')}\n\n"
            if status.get("config_changed_on_disk", False):
                error_message += "Config has changed on disk.\n\n"
            error_message += "Full config details:\n"
            error_message += json.dumps(
                status.get("config_details", {}), indent=2)

            error_text.insert(tkinter.END, error_message)
            error_text.config(state=tkinter.DISABLED)

    # Add this at the end of the function
    def on_close():
        global status_window
        status_window.destroy()
        status_window = None

    status_window.protocol("WM_DELETE_WINDOW", on_close)
    status_window.mainloop()


def open_config_file():
    config_file_path = get_config_file_path()
    if config_file_path:
        config_dir = os.path.dirname(config_file_path)
        if os.name == 'nt':  # For Windows
            os.startfile(config_dir)
        elif os.name == 'posix':  # For macOS and Linux
            subprocess.call(('xdg-open', config_dir))
    else:
        log_message("Config file path not found", level=logging.ERROR)


def open_log_folder():
    log_file_path = get_log_file_path()
    if log_file_path:
        log_dir = os.path.dirname(log_file_path)
        if os.name == 'nt':  # For Windows
            os.startfile(log_dir)
        elif os.name == 'posix':  # For macOS and Linux
            subprocess.call(('xdg-open', log_dir))
    else:
        log_message("Log file path not found", level=logging.ERROR)


def get_config_file_path():
    status = get_daemon_status()
    return status.get('config_file_location')


def get_log_file_path():
    status = get_daemon_status()
    return status.get('log_file_location')


def show_text_window(title, content):
    root = tkinter.Tk()
    root.title(title)
    root.geometry("600x400")

    text_widget = tkinter.Text(root, wrap=tkinter.WORD)
    text_widget.pack(expand=True, fill='both')
    text_widget.insert(tkinter.END, content)
    text_widget.config(state=tkinter.DISABLED)

    scrollbar = ttk.Scrollbar(root, orient="vertical",
                              command=text_widget.yview)
    scrollbar.pack(side=tkinter.RIGHT, fill=tkinter.Y)
    text_widget.configure(yscrollcommand=scrollbar.set)

    root.mainloop()


def ensure_daemon_running():
    global daemon_manager
    timeout = 30  # Timeout in seconds
    interval = 1  # Check interval in seconds

    status = get_daemon_status()
    if status is not None:
        log_message("Daemon is already running", level=logging.INFO)
        return True

    log_message("Daemon not running. Attempting to start it.",
                level=logging.INFO)

    start_daemon()

    if daemon_manager.daemon_start_error:
        log_message(f"Failed to start daemon: {
                    daemon_manager.daemon_start_error}", level=logging.ERROR)
        return False

    elapsed_time = 0
    while elapsed_time < timeout:
        log_message(f"Checking daemon status: Elapsed time {
                    elapsed_time}s", level=logging.DEBUG)
        status = get_daemon_status()
        if status is not None:
            log_message("Daemon started successfully", level=logging.INFO)
            return True
        time.sleep(interval)
        elapsed_time += interval

    log_message("Failed to start daemon within the timeout period",
                level=logging.ERROR)
    return False


def clear_crash_log():
    crash_log_path = '/tmp/rclone_bisync_manager_crash.log'
    if os.path.exists(crash_log_path):
        try:
            os.remove(crash_log_path)
            log_message("Cleared existing crash log", level=logging.INFO)
        except Exception as e:
            log_message(f"Error clearing crash log: {e}", level=logging.ERROR)


def run_tray():
    global icon, daemon_manager, args, debug, update_queue
    daemon_manager = DaemonManager()
    update_queue = Queue()

    parser = argparse.ArgumentParser()
    parser.add_argument('--icon-style', type=int,
                        choices=[1, 2], default=1, help='Choose icon style: 1 or 2')
    parser.add_argument('--icon-thickness', type=int,
                        default=40, help='Set the thickness of the icon lines')
    parser.add_argument('--log-level', type=str, choices=['NONE', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='NONE', help='Set the logging level')
    parser.add_argument('--enable-experimental', action='store_true',
                        help='Enable experimental features')
    parser.add_argument('--config', type=str,
                        help='Specify a custom config file location')
    args = parser.parse_args()

    # Set up logging based on the argument
    if args.log_level != 'NONE':
        logging.basicConfig(level=getattr(logging, args.log_level),
                            format='%(asctime)s - %(levelname)s - %(message)s')
        debug = (args.log_level == 'DEBUG')
    else:
        logging.disable(logging.CRITICAL)  # Disable all logging
        debug = False

    clear_crash_log()  # Clear the crash log before starting

    initial_status = get_daemon_status()
    initial_state = daemon_manager.get_current_state(initial_status)

    icon = pystray.Icon("rclone-bisync-manager",
                        create_status_image(daemon_manager.get_icon_color(initial_status),
                                            daemon_manager.get_icon_text(
                                                initial_status),
                                            style=args.icon_style,
                                            thickness=args.icon_thickness),
                        "RClone BiSync Manager")

    icon.menu = pystray.Menu(*daemon_manager.get_menu_items(initial_status))

    Thread(target=check_status_and_update, daemon=True).start()
    Thread(target=handle_updates, daemon=True).start()

    # Start the daemon only if the initial state is OFFLINE
    if initial_state == DaemonState.OFFLINE:
        Thread(target=start_daemon, daemon=True).start()

    try:
        icon.run()
    except KeyboardInterrupt:
        exit_tray()


def update_menu_and_icon():
    global icon, daemon_manager, args
    current_status = get_daemon_status()
    current_state = daemon_manager.get_current_state(current_status)

    log_message(f"Updating menu and icon. Current state: {
                current_state.name}", level=logging.INFO)

    # Log the current menu items
    log_message("Current menu items:", level=logging.DEBUG)
    for item in icon.menu:
        log_message(f"  - {item.text}", level=logging.DEBUG)

    # Get new menu items and log them
    new_menu_items = daemon_manager.get_menu_items(current_status)
    log_message("New menu items:", level=logging.DEBUG)
    for item in new_menu_items:
        log_message(f"  - {item.text}", level=logging.DEBUG)

    new_menu = pystray.Menu(*new_menu_items)
    new_icon_color = daemon_manager.get_icon_color(current_status)
    new_icon_text = daemon_manager.get_icon_text(current_status)

    log_message(f"New icon color: {new_icon_color}", level=logging.DEBUG)
    log_message(f"New icon text: {new_icon_text}", level=logging.DEBUG)

    new_icon = create_status_image(
        new_icon_color,
        new_icon_text,
        style=args.icon_style,
        thickness=args.icon_thickness
    )

    # Check if there are actual changes
    menu_changed = str(new_menu) != str(icon.menu)
    icon_changed = new_icon != icon.icon

    log_message(f"Menu changed: {menu_changed}", level=logging.DEBUG)
    log_message(f"Icon changed: {icon_changed}", level=logging.DEBUG)

    if menu_changed or icon_changed:
        icon.menu = new_menu
        icon.icon = new_icon
        icon.update_menu()
        log_message(f"Menu and icon updated for state: {
                    current_state.name}", level=logging.INFO)
    else:
        log_message("No changes detected, skipping update", level=logging.INFO)


def check_status_and_update():
    global daemon_manager
    last_status = None
    while True:
        try:
            crash_message = check_crash_log()
            if crash_message:
                current_state = DaemonState.FAILED
                if daemon_manager.update_state(current_state) or daemon_manager.daemon_start_error != crash_message:
                    daemon_manager.daemon_start_error = crash_message
                    update_queue.put(True)
                    log_message(f"Daemon crashed. Current state: {
                                current_state.name}", level=logging.ERROR)
                    log_message(f"Crash message: {
                                crash_message}", level=logging.ERROR)
                continue

            current_status = get_daemon_status()
            current_state = daemon_manager.get_current_state(current_status)

            # Update the daemon manager state
            state_changed = daemon_manager.update_state(current_state)

            # Check if the status or state has changed
            if current_status != last_status or state_changed:
                log_message(
                    "Status or state changed. Updating menu and icon.", level=logging.INFO)
                log_message(f"New status: {
                            current_status}", level=logging.DEBUG)
                update_queue.put(True)

            last_status = current_status

        except Exception as e:
            log_message(f"Error in check_status_and_update: {
                        e}", level=logging.ERROR)
            log_message(f"Error details: {
                        traceback.format_exc()}", level=logging.DEBUG)

        time.sleep(1)


def handle_updates():
    while True:
        try:
            update_queue.get()
            update_menu_and_icon()
        except Exception as e:
            log_message(f"Error in handle_updates: {e}", level=logging.ERROR)
            log_message(f"Error details: {
                        traceback.format_exc()}", level=logging.DEBUG)
        finally:
            update_queue.task_done()


def check_crash_log():
    crash_log_path = '/tmp/rclone_bisync_manager_crash.log'
    if os.path.exists(crash_log_path):
        with open(crash_log_path, 'r') as f:
            crash_message = f.read()
        # os.remove(crash_log_path)  # Remove the file after reading
        return crash_message
    return None


def edit_config():
    global daemon_manager
    try:
        config_file = daemon_manager.get_config_file_path()
        if config_file:
            from rclone_bisync_manager_tray.config_editor import edit_config as config_editor
            config_editor(config_file)
            reload_config()
        else:
            log_message("Config file path not available", level=logging.ERROR)
            messagebox.showerror("Error", "Config file path not available")
    except Exception as e:
        log_message(f"Error editing config: {str(e)}", level=logging.ERROR)
        messagebox.showerror("Error", f"Failed to edit config: {str(e)}")


def exit_tray():
    log_message("Exiting tray application", level=logging.INFO)
    icon.stop()
    sys.exit(0)


def show_notification(title, message):
    global icon
    if icon:
        icon.notify(message, title)
    else:
        log_message(f"Notification: {title} - {message}", level=logging.INFO)


def main():
    run_tray()


if __name__ == "__main__":
    main()
