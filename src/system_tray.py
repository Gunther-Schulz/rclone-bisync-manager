#!/usr/bin/env python3

import pystray
from PIL import Image
import socket
import json
import threading
import time


def get_daemon_status():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(socket_path)
        status = json.loads(client.recv(4096).decode())
        client.close()
        return status
    except Exception as e:
        return {"error": str(e)}


def update_menu():
    status = dict(get_daemon_status())
    if "error" in status:
        return pystray.Menu(pystray.MenuItem("Daemon not running", lambda: None))

    menu_items = [
        pystray.MenuItem(f"Currently syncing: {status.get(
            'currently_syncing', 'None')}", lambda: None),
        pystray.MenuItem(f"Queued jobs: {', '.join(
            status.get('queued_paths', [])) or 'None'}", lambda: None),
        pystray.MenuItem("Stop Daemon", stop_daemon),
        pystray.MenuItem("Exit", lambda: icon.stop()),
    ]

    return pystray.Menu(*menu_items)


def stop_daemon():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(socket_path)
        status = json.loads(client.recv(4096).decode())
        client.close()
        if 'pid' in status:
            import os
            import signal
            os.kill(status['pid'], signal.SIGTERM)
            print("Sent stop signal to daemon")
    except Exception as e:
        print(f"Error stopping daemon: {e}")


def run_tray():
    global icon
    image = Image.new('RGB', (64, 64), color=(255, 0, 0))
    icon = pystray.Icon("rclone-bisync-manager",
                        image, "RClone BiSync Manager")
    icon.menu = update_menu()

    def check_status_and_update():
        last_status = None
        while True:
            current_status = get_daemon_status()
            if current_status != last_status:
                icon.update_menu()
                last_status = current_status
            time.sleep(5)

    threading.Thread(target=check_status_and_update, daemon=True).start()
    icon.run()


if __name__ == "__main__":
    run_tray()
