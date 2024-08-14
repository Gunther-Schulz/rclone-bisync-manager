#!/usr/bin/env python3

import pystray
from PIL import Image, ImageDraw
import socket
import json
import threading
import time
import os


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


def update_menu(status):
    if "error" in status:
        return pystray.Menu(pystray.MenuItem("Daemon not running", lambda: None))

    menu_items = []

    if "sync_jobs" in status:
        for job_key, job_status in status["sync_jobs"].items():
            job_submenu = pystray.Menu(
                pystray.MenuItem(
                    f"Last sync: {job_status['last_sync'] or 'Never'}", lambda: None),
                pystray.MenuItem(
                    f"Next run: {job_status['next_run'] or 'Not scheduled'}", lambda: None),
                pystray.MenuItem(
                    f"Sync status: {job_status['sync_status']}", lambda: None),
                pystray.MenuItem(f"Resync status: {
                                 job_status['resync_status']}", lambda: None)
            )
            menu_items.append(pystray.MenuItem(f"Job: {job_key}", job_submenu))

    menu_items.extend([
        pystray.MenuItem(f"Currently syncing: {status.get(
            'currently_syncing', 'None')}", lambda: None),
        pystray.MenuItem(f"Queued jobs: {', '.join(
            status.get('queued_paths', [])) or 'None'}", lambda: None),
        pystray.MenuItem("Reload Config", reload_config),
        pystray.MenuItem("Stop Daemon", stop_daemon),
        pystray.MenuItem("Exit", lambda: icon.stop()),
    ])

    return pystray.Menu(*menu_items)


def stop_daemon():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(socket_path)
        client.sendall(b"STOP")
        response = client.recv(1024).decode()
        client.close()
        print(response)
    except Exception as e:
        print(f"Error stopping daemon: {e}")


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
                print(response_data["message"])
            else:
                print(f"Error: {response_data['message']}")
            return response_data["status"] == "success"
        except json.JSONDecodeError:
            print(f"Error: Invalid response from daemon: {response}")
            return False
    except Exception as e:
        print(f"Error communicating with daemon: {str(e)}")
        return False


def create_arrow_image(color):
    size = 64
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Draw two half-circle arrows
    padding = 8
    line_width = 6

    # First arrow (top half)
    draw.arc((padding, padding, size - padding, size - padding),
             start=20, end=160, fill=color, width=line_width)
    # First arrowhead
    draw.polygon([
        (size - padding - 5, size // 2 - 13),
        (size - padding + 5, size // 2 - 3),
        (size - padding - 7, size // 2 + 2)
    ], fill=color)

    # Second arrow (bottom half)
    draw.arc((padding, padding, size - padding, size - padding),
             start=200, end=340, fill=color, width=line_width)
    # Second arrowhead
    draw.polygon([
        (padding + 5, size // 2 + 13),
        (padding - 5, size // 2 + 3),
        (padding + 7, size // 2 - 2)
    ], fill=color)

    return image


def run_tray():
    global icon
    red_image = create_arrow_image((255, 0, 0))
    green_image = create_arrow_image((0, 255, 0))
    yellow_image = create_arrow_image((255, 255, 0))

    icon = pystray.Icon("rclone-bisync-manager",
                        red_image, "RClone BiSync Manager")
    icon.menu = update_menu({"error": "Initial state"})

    def check_status_and_update():
        last_status = None
        while True:
            current_status = get_daemon_status()
            if current_status != last_status:
                new_menu = update_menu(current_status)
                icon.menu = new_menu
                if "error" not in current_status:
                    if current_status.get("currently_syncing"):
                        icon.icon = yellow_image
                    else:
                        icon.icon = green_image
                else:
                    icon.icon = red_image
                icon.update_menu()
                last_status = current_status
            time.sleep(1)  # Changed from 5 to 1 second

    threading.Thread(target=check_status_and_update, daemon=True).start()
    icon.run()


if __name__ == "__main__":
    run_tray()
