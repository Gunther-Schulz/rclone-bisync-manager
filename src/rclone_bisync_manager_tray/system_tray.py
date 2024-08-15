#!/usr/bin/env python3

import tkinter
from tkinter import ttk
import pystray
from PIL import Image, ImageDraw
import socket
import json
import threading
import time
import subprocess


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


def update_menu(status):
    if "error" in status:
        return pystray.Menu(
            pystray.MenuItem("Daemon not running", None, enabled=False),
            pystray.MenuItem("Start Daemon", start_daemon)
        )

    menu_items = []

    # Add warning state at the top of the menu
    has_sync_issues = any(
        job["sync_status"] not in ["COMPLETED", "NONE", None] or
        job["resync_status"] not in ["COMPLETED", "NONE", None] or
        job.get("hash_warnings", False)
        for job in status.get("sync_jobs", {}).values()
    )
    if has_sync_issues:
        menu_items.append(pystray.MenuItem(
            "⚠️ Sync issues detected", None, enabled=False))

    currently_syncing = status.get('currently_syncing', 'None')
    menu_items.append(pystray.MenuItem(f"Currently syncing:\n  {
                      currently_syncing}", None, enabled=False))

    queued_jobs = status.get('queued_paths', [])
    if queued_jobs:
        queued_jobs_str = "Queued jobs:\n" + \
            "\n".join(f"  {job}" for job in queued_jobs)
        menu_items.append(pystray.MenuItem(
            queued_jobs_str, None, enabled=False))
    else:
        menu_items.append(pystray.MenuItem(
            "Queued jobs:\n  None", None, enabled=False))

    if "sync_jobs" in status:
        jobs_submenu = []
        for job_key, job_status in status["sync_jobs"].items():
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
                    "⚡ Sync now", create_sync_now_handler(job_key)),
                # Empty text field below Sync now
                pystray.MenuItem("", None, enabled=False)
            )
            jobs_submenu.append(pystray.MenuItem(
                f"Job: {job_key}", job_submenu))

        menu_items.append(pystray.MenuItem(
            "Sync Jobs", pystray.Menu(*jobs_submenu)))

    menu_items.extend([
        pystray.MenuItem("Show Status Window", show_status_window),
        pystray.MenuItem("Reload Config", reload_config),
        pystray.MenuItem("Stop Daemon", stop_daemon),
        pystray.MenuItem("Exit", lambda: icon.stop())
    ])

    # Add config status at the bottom
    config_status = "Valid" if not status.get(
        "config_invalid", False) else "Invalid"
    menu_items.append(pystray.MenuItem(
        f"Config:\n  {config_status}", None, enabled=False))

    return pystray.Menu(*menu_items)


def reload_config():
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
            icon.menu = update_menu(current_status)

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
        # client.sendall(json.dumps(job_key).encode())
        client.sendall(json.dumps([job_key]).encode())
        response = client.recv(1024).decode()
        client.close()
        print(f"Add to sync queue response: {response}")
    except Exception as e:
        print(f"Error adding job to sync queue: {str(e)}")


def determine_arrow_color(status, bg_color):
    if isinstance(status, str):
        return "black" if status == "error" else "black"

    if bg_color == (0, 120, 255):  # Blue background
        return "black"

    if status.get("config_invalid") or status.get("config_error_message"):
        return "red"

    has_sync_issues = False
    if "sync_jobs" in status:
        for job_key, job_status in status["sync_jobs"].items():
            if (job_status["sync_status"] not in ["COMPLETED", "NONE", None] or
                    job_status["resync_status"] not in ["COMPLETED", "NONE", None] or
                    job_status.get("hash_warnings", False)):
                has_sync_issues = True
                break

    if has_sync_issues:
        return "yellow"  # New warning state for sync issues

    return "green"


def create_status_image(color, status):
    size = 64
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.ellipse([0, 0, size, size], fill=color)

    arrow_color = determine_arrow_color(status, color)
    if isinstance(status, str) and status == "error":
        arrow_color = "black"  # Force black color for error state

    if arrow_color != "white":
        draw.arc([8, 8, size-8, size-8], start=0,
                 end=270, fill=arrow_color, width=8)
        draw.arc([4, 4, size-4, size-4], start=250,
                 end=270, fill=arrow_color, width=16)
        draw.polygon([
            (size-4, size//2),
            (size-12, size//2-8),
            (size-12, size//2+8)
        ], fill=arrow_color)
    else:
        draw.line([(16, 16), (48, 48)], fill='white', width=8)
        draw.line([(16, 48), (48, 16)], fill='white', width=8)

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


def run_tray():
    global icon
    error_image = create_status_image((255, 0, 0), 'error')

    icon = pystray.Icon("rclone-bisync-manager",
                        error_image, "RClone BiSync Manager")
    icon.menu = update_menu({"error": "Initial state"})

    def check_status_and_update():
        last_status = None
        while True:
            current_status = get_daemon_status()
            if current_status != last_status:
                new_menu = update_menu(current_status)
                icon.menu = new_menu
                if "error" in current_status:
                    icon.icon = create_status_image(
                        (255, 0, 0), "error")  # Red for error
                elif current_status.get("shutting_down", False):
                    icon.icon = create_status_image(
                        # Orange for shutting down
                        (255, 165, 0), "shutting_down")
                elif current_status.get("currently_syncing"):
                    icon.icon = create_status_image(
                        (0, 120, 255), current_status)  # Blue for syncing
                else:
                    if current_status.get("config_invalid"):
                        # Light yellow for config invalid
                        icon.icon = create_status_image(
                            (255, 200, 0), current_status)
                    elif any(job["sync_status"] not in ["COMPLETED", "NONE", None] or
                             job["resync_status"] not in ["COMPLETED", "NONE", None] or
                             job.get("hash_warnings", False)
                             for job in current_status.get("sync_jobs", {}).values()):
                        icon.icon = create_status_image(
                            # Yellow for sync issues
                            (255, 255, 0), current_status)
                    else:
                        icon.icon = create_status_image(
                            (0, 200, 0), current_status)  # Green for running
                icon.update_menu()
                last_status = current_status
            time.sleep(1)

    threading.Thread(target=check_status_and_update, daemon=True).start()
    icon.run()


def main():
    run_tray()


if __name__ == "__main__":
    main()
