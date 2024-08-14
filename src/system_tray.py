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

    menu_items = [
        pystray.MenuItem(f"Currently syncing: {status.get(
            'currently_syncing', 'None')}", lambda: None),
        pystray.MenuItem(f"Queued jobs: {', '.join(
            status.get('queued_paths', [])) or 'None'}", lambda: None),
        pystray.MenuItem("Reload Config", reload_config),
        pystray.MenuItem("Stop Daemon", stop_daemon),
        pystray.MenuItem("Exit", lambda: icon.stop()),
    ]

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
        print(response)
    except Exception as e:
        print(f"Error reloading daemon configuration: {e}")


def create_circle_image(color):
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([0, 0, 64, 64], fill=color)
    return image


def run_tray():
    global icon
    red_image = create_circle_image((255, 0, 0))
    green_image = create_circle_image((0, 255, 0))
    yellow_image = create_circle_image((255, 255, 0))

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
