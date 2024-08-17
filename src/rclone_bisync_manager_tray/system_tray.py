#!/usr/bin/env python3

from PIL import ImageFont
from pystray import MenuItem as item
import tkinter
from tkinter import ttk
import pystray
from PIL import Image, ImageDraw
import socket
import json
import threading
import time
import subprocess
import os
import enum
from dataclasses import dataclass

global daemon_manager
daemon_manager = None


class DaemonState(enum.Enum):
    INITIAL = "initial"
    STARTING = "starting"
    RUNNING = "running"
    SYNCING = "syncing"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"
    SYNC_ISSUES = "sync_issues"
    CONFIG_INVALID = "config_invalid"
    CONFIG_CHANGED = "config_changed"


@dataclass
class StateInfo:
    color: tuple
    menu_items: list
    icon_text: str


class DaemonManager:
    def __init__(self):
        self.state = DaemonState.INITIAL
        self.status = {}
        self.state_info = {
            DaemonState.INITIAL: StateInfo((255, 235, 59), self._get_initial_menu_items, "INIT"),
            DaemonState.STARTING: StateInfo((255, 235, 59), self._get_starting_menu_items, "START"),
            DaemonState.RUNNING: StateInfo((76, 175, 80), self._get_running_menu_items, "RUN"),
            DaemonState.SYNCING: StateInfo((33, 150, 243), self._get_running_menu_items, "SYNC"),
            DaemonState.ERROR: StateInfo((158, 158, 158), self._get_error_menu_items, "ERR"),
            DaemonState.SHUTTING_DOWN: StateInfo((156, 39, 176), self._get_shutting_down_menu_items, "STOP"),
            DaemonState.SYNC_ISSUES: StateInfo((255, 152, 0), self._get_running_menu_items, "WARN"),
            DaemonState.CONFIG_INVALID: StateInfo((244, 67, 54), self._get_running_menu_items, "CFG!"),
            DaemonState.CONFIG_CHANGED: StateInfo((255, 193, 7), self._get_running_menu_items, "CFG?"),
        }

    def update_state(self, status):
        self.status = status
        if "error" in status:
            self.state = DaemonState.ERROR
        elif status.get("shutting_down"):
            self.state = DaemonState.SHUTTING_DOWN
        elif status.get("starting_up"):
            self.state = DaemonState.STARTING
        elif status.get("config_invalid"):
            self.state = DaemonState.CONFIG_INVALID
        elif status.get("config_changed_on_disk"):
            self.state = DaemonState.CONFIG_CHANGED
        elif status.get("currently_syncing"):
            self.state = DaemonState.SYNCING
        elif self._has_sync_issues(status):
            self.state = DaemonState.SYNC_ISSUES
        else:
            self.state = DaemonState.RUNNING

    def _has_sync_issues(self, status):
        return any(
            job["sync_status"] not in ["COMPLETED", "NONE", None] or
            job["resync_status"] not in ["COMPLETED", "NONE", None] or
            job.get("hash_warnings", False)
            for job in status.get("sync_jobs", {}).values()
        )

    def _get_initial_menu_items(self):
        return [
            pystray.MenuItem("Starting...", None, enabled=False),
            pystray.MenuItem("Exit", lambda: icon.stop())
        ]

    def _get_starting_menu_items(self):
        return [
            pystray.MenuItem("Starting daemon...", None, enabled=False),
            pystray.MenuItem("Exit", lambda: icon.stop())
        ]

    def _get_error_menu_items(self):
        return [
            pystray.MenuItem("Start Daemon", start_daemon),
            pystray.MenuItem("Exit", lambda: icon.stop())
        ]

    def _get_shutting_down_menu_items(self):
        return [
            pystray.MenuItem("Shutting down...", None, enabled=False),
            pystray.MenuItem("Exit", lambda: icon.stop())
        ]

    def _get_running_menu_items(self):
        menu_items = []

        # Add warning state at the top of the menu
        has_sync_issues = any(
            job["sync_status"] not in ["COMPLETED", "NONE", None] or
            job["resync_status"] not in ["COMPLETED", "NONE", None] or
            job.get("hash_warnings", False)
            for job in self.status.get("sync_jobs", {}).values()
        )
        if has_sync_issues:
            menu_items.append(pystray.MenuItem(
                "⚠️ Sync issues detected", None, enabled=False))

        currently_syncing = self.status.get('currently_syncing', 'None')
        menu_items.append(pystray.MenuItem(f"Currently syncing:\n  {
                          currently_syncing}", None, enabled=False))

        queued_jobs = self.status.get('queued_paths', [])
        if queued_jobs:
            queued_jobs_str = "Queued jobs:\n" + \
                "\n".join(f"  {job}" for job in queued_jobs)
            menu_items.append(pystray.MenuItem(
                queued_jobs_str, None, enabled=False))
        else:
            menu_items.append(pystray.MenuItem(
                "Queued jobs:\n  None", None, enabled=False))

        # Add a separator before "Sync Jobs"
        menu_items.append(pystray.Menu.SEPARATOR)

        is_shutting_down = self.status.get('shutting_down', False)

        if "sync_jobs" in self.status and not self.status.get('config_invalid', False) and not is_shutting_down:
            jobs_submenu = []
            for job_key, job_status in reversed(self.status["sync_jobs"].items()):
                job_submenu = pystray.Menu(
                    pystray.MenuItem(
                        f"Last sync: {job_status['last_sync'] or 'Never'}", None, enabled=False),
                    pystray.MenuItem(
                        f"Next run: {job_status['next_run'] or 'Not scheduled'}", None, enabled=False),
                    pystray.MenuItem(
                        f"Sync status: {job_status['sync_status']}", None, enabled=False),
                    pystray.MenuItem(f"Resync status: {
                                     job_status['resync_status']}", None, enabled=False),
                    pystray.MenuItem(
                        "⚡ Sync Now", create_sync_now_handler(job_key)),
                    pystray.MenuItem("", None, enabled=False)
                )
                jobs_submenu.append(pystray.MenuItem(
                    f"Job: {job_key}", job_submenu))

            menu_items.append(pystray.MenuItem(
                "Sync Jobs", pystray.Menu(*reversed(jobs_submenu))))
        else:
            menu_items.append(pystray.MenuItem(
                "Sync Jobs", None, enabled=False))

        menu_items.extend([
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Config & Logs", pystray.Menu(
                pystray.MenuItem("Reload Config", reload_config,
                                 enabled=self.status.get('currently_syncing') == None and not is_shutting_down),
                pystray.MenuItem("Open Config Folder", open_config_file),
                pystray.MenuItem("Open Log Folder", open_log_folder)
            )),
            pystray.MenuItem("⚠️ Config file is invalid",
                             None, enabled=False, visible=self.status.get('config_invalid', False)),
            pystray.MenuItem("⚠️ Config changed on disk",
                             None, enabled=False,
                             visible=not self.status.get('config_invalid', False) and self.status.get('config_changed_on_disk', False)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show Status Window", show_status_window,
                             enabled=not is_shutting_down),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Shutting down..." if is_shutting_down else "Stop Daemon",
                             stop_daemon, enabled=not is_shutting_down),
            pystray.MenuItem("Exit", lambda: icon.stop())
        ])

        return menu_items

    def get_icon_color(self):
        return self.state_info[self.state].color

    def get_menu_items(self):
        items = self.state_info[self.state].menu_items
        return items() if callable(items) else items

    def get_icon_text(self):
        return self.state_info[self.state].icon_text


def get_daemon_status():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(socket_path)
        client.sendall(b"STATUS")
        status = json.loads(client.recv(4096).decode())
        client.close()
        return status
    except Exception as e:
        return {"error": str(e)}


def create_sync_now_handler(job_key):
    def handler(item):
        add_to_sync_queue(job_key)
    return handler


def stop_daemon():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(socket_path)
        client.sendall(b"STOP")
        response = client.recv(1024).decode()
        client.close()
        print("Daemon is shutting down. Use 'daemon status' to check progress.")
    except Exception as e:
        print(f"Error stopping daemon: {e}")


def start_daemon():
    try:
        subprocess.run(
            ["rclone-bisync-manager", "daemon", "start"], check=True)
        print("Daemon started successfully")
    except subprocess.CalledProcessError as e:
        print(f"Error starting daemon: {e}")


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
                print("Configuration reloaded successfully")
            else:
                print(f"Error reloading configuration: {
                      response_data['message']}")

            current_status = get_daemon_status()
            daemon_manager.update_state(current_status)
            icon.menu = pystray.Menu(*daemon_manager.get_menu_items())
            icon.update_menu()

            return response_data["status"] == "success"
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON response from daemon: {response}")
            return False
    except Exception as e:
        print(f"Error communicating with daemon: {str(e)}")
        return False


def add_to_sync_queue(job_key):
    socket_path = '/tmp/rclone_bisync_manager_add_sync.sock'
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(socket_path)
        client.sendall(json.dumps([job_key]).encode())
        response = client.recv(1024).decode()
        client.close()
        print(f"Add to sync queue response: {response}")
    except Exception as e:
        print(f"Error adding job to sync queue: {str(e)}")


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


def create_status_image(color, icon_text):
    size = 64
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Draw background circle
    draw.ellipse([0, 0, size, size], fill=color)

    # Determine arrow color
    arrow_color = determine_arrow_color(color, icon_text)

    # Draw arrows
    arrow_width = 4
    arrow_padding = 12
    arrow_size = size - 2 * arrow_padding

    # Top arrow (pointing right)
    draw.line((arrow_padding, size//2 - arrow_size//4,
               size - arrow_padding, size//2 - arrow_size//4),
              fill=arrow_color, width=arrow_width)
    draw.polygon([(size - arrow_padding, size//2 - arrow_size//4),
                  (size - arrow_padding - arrow_size//6,
                   size//2 - arrow_size//4 - arrow_size//6),
                  (size - arrow_padding - arrow_size//6, size//2 - arrow_size//4 + arrow_size//6)],
                 fill=arrow_color)

    # Bottom arrow (pointing left)
    draw.line((size - arrow_padding, size//2 + arrow_size//4,
               arrow_padding, size//2 + arrow_size//4),
              fill=arrow_color, width=arrow_width)
    draw.polygon([(arrow_padding, size//2 + arrow_size//4),
                  (arrow_padding + arrow_size//6, size //
                   2 + arrow_size//4 - arrow_size//6),
                  (arrow_padding + arrow_size//6, size//2 + arrow_size//4 + arrow_size//6)],
                 fill=arrow_color)

    # Draw icon text
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    left, top, right, bottom = draw.textbbox((0, 0), icon_text, font=font)
    text_width = right - left
    text_height = bottom - top
    text_position = ((size - text_width) // 2, (size - text_height) // 2)
    draw.text(text_position, icon_text, font=font, fill=arrow_color)

    return image


def show_status_window():
    status = get_daemon_status()

    window = tkinter.Tk()
    window.title("RClone BiSync Manager Status")
    window.geometry("400x300")

    style = ttk.Style()
    style.theme_use('clam')

    notebook = ttk.Notebook(window)
    notebook.pack(expand=True, fill='both')

    general_frame = ttk.Frame(notebook)
    notebook.add(general_frame, text='General')

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
                      job_status['last_sync'] or 'Never'}").pack(anchor='w')
            ttk.Label(job_frame, text=f"Next run: {
                      job_status['next_run'] or 'Not scheduled'}").pack(anchor='w')
            ttk.Label(job_frame, text=f"Sync status: {
                      job_status['sync_status']}").pack(anchor='w')
            ttk.Label(job_frame, text=f"Resync status: {
                      job_status['resync_status']}").pack(anchor='w')

    window.mainloop()


def open_config_file():
    config_file_path = get_config_file_path()
    if config_file_path:
        config_dir = os.path.dirname(config_file_path)
        if os.name == 'nt':  # For Windows
            os.startfile(config_dir)
        elif os.name == 'posix':  # For macOS and Linux
            subprocess.call(('xdg-open', config_dir))
    else:
        print("Config file path not found")


def open_log_folder():
    log_file_path = get_log_file_path()
    if log_file_path:
        log_dir = os.path.dirname(log_file_path)
        if os.name == 'nt':  # For Windows
            os.startfile(log_dir)
        elif os.name == 'posix':  # For macOS and Linux
            subprocess.call(('xdg-open', log_dir))
    else:
        print("Log file path not found")


def get_config_file_path():
    status = get_daemon_status()
    return status.get('config_file_location')


def get_log_file_path():
    status = get_daemon_status()
    return status.get('log_file_location')


def run_tray():
    global icon, daemon_manager
    daemon_manager = DaemonManager()

    icon = pystray.Icon("rclone-bisync-manager",
                        create_status_image(
                            daemon_manager.get_icon_color(), daemon_manager.get_icon_text()),
                        "RClone BiSync Manager")
    icon.menu = pystray.Menu(*daemon_manager.get_menu_items())

    def check_status_and_update():
        initial_startup = True
        last_state = None
        last_status = None

        while True:
            current_status = get_daemon_status()

            if initial_startup:
                if "error" in current_status:
                    print("Daemon not running. Attempting to start...")
                    start_daemon()
                    time.sleep(5)  # Wait for the daemon to start
                    current_status = get_daemon_status()
                initial_startup = False

            daemon_manager.update_state(current_status)
            current_state = daemon_manager.state

            if current_state != last_state or current_status != last_status:
                new_menu = pystray.Menu(*daemon_manager.get_menu_items())
                icon.menu = new_menu
                icon.icon = create_status_image(
                    daemon_manager.get_icon_color(), daemon_manager.get_icon_text())
                icon.update_menu()

                last_state = current_state
                last_status = current_status

            time.sleep(1)

    threading.Thread(target=check_status_and_update, daemon=True).start()
    icon.run()


def main():
    run_tray()


if __name__ == "__main__":
    main()
