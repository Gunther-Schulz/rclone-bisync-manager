#!/usr/bin/env python3

import pystray
from PIL import Image, ImageDraw
import socket
import json
import threading
import time
import os
from config import debug
import tkinter as tk
from tkinter import ttk


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
        return pystray.Menu(pystray.MenuItem("Daemon not running", None, enabled=False))

    menu_items = []

    # Add config status item as non-interactive text
    config_status = "Valid" if not status.get(
        "config_invalid", False) else "Invalid"
    menu_items.append(pystray.MenuItem(
        f"Config: {config_status}", None, enabled=False))

    # Add currently syncing item
    menu_items.append(pystray.MenuItem(f"Currently syncing: {
                      status.get('currently_syncing', 'None')}", None, enabled=False))

    # Add queued jobs item
    menu_items.append(pystray.MenuItem(f"Queued jobs: {', '.join(
        status.get('queued_paths', [])) or 'None'}", None, enabled=False))

    # Add sync jobs submenu
    if "sync_jobs" in status:
        for job_key, job_status in status["sync_jobs"].items():
            job_submenu = pystray.Menu(
                pystray.MenuItem(
                    f"Last sync: {job_status['last_sync'] or 'Never'}", None, enabled=False),
                pystray.MenuItem(
                    f"Next run: {job_status['next_run'] or 'Not scheduled'}", None, enabled=False),
                pystray.MenuItem(
                    f"Sync status: {job_status['sync_status']}", None, enabled=False),
                pystray.MenuItem(f"Resync status: {
                                 job_status['resync_status']}", None, enabled=False)
            )
            menu_items.append(pystray.MenuItem(f"Job: {job_key}", job_submenu))

    # Add interactive menu items
    menu_items.extend([
        pystray.MenuItem("Show Status Window", show_status_window),
        pystray.MenuItem("Reload Config", reload_config),
        pystray.MenuItem("Stop Daemon", stop_daemon),
        pystray.MenuItem("Exit", lambda: icon.stop())
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
                if debug:
                    print(response_data["message"])
            else:
                if debug:
                    print(f"Error: {response_data['message']}")

            # Update the tray icon immediately
            current_status = get_daemon_status()
            icon.menu = update_menu(current_status)

            return response_data["status"] == "success"
        except json.JSONDecodeError:
            if debug:
                print(f"Error: Invalid JSON response from daemon: {response}")
            return False
    except Exception as e:
        if debug:
            print(f"Error communicating with daemon: {str(e)}")
        return False


def create_status_image(color, status):
    size = 64
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Draw circle
    draw.ellipse([0, 0, size, size], fill=color)

    # Draw status symbol
    if status in ['running', 'syncing', 'config_invalid']:
        arrow_color = 'black'
        # Arc
        draw.arc([8, 8, size-8, size-8], start=0,
                 end=270, fill=arrow_color, width=8)
        # Curved arrow head
        draw.arc([4, 4, size-4, size-4], start=250,
                 end=270, fill=arrow_color, width=16)
        # Arrow tip
        draw.polygon([
            (size-4, size//2),
            (size-12, size//2-8),
            (size-12, size//2+8)
        ], fill=arrow_color)
    elif status == 'error':
        # X mark
        draw.line([(16, 16), (48, 48)], fill='white', width=8)
        draw.line([(16, 48), (48, 16)], fill='white', width=8)

    return image


def show_status_window():
    status = get_daemon_status()

    window = tk.Tk()
    window.title("RClone BiSync Manager Status")
    window.geometry("400x300")

    style = ttk.Style()
    style.theme_use('clam')

    notebook = ttk.Notebook(window)
    notebook.pack(expand=True, fill='both')

    # General Status Tab
    general_frame = ttk.Frame(notebook)
    notebook.add(general_frame, text='General')

    ttk.Label(general_frame, text=f"Config: {'Valid' if not status.get(
        'config_invalid', False) else 'Invalid'}").pack(pady=5)
    ttk.Label(general_frame, text=f"Currently syncing: {
              status.get('currently_syncing', 'None')}").pack(pady=5)
    ttk.Label(general_frame, text=f"Queued jobs: {', '.join(
        status.get('queued_paths', [])) or 'None'}").pack(pady=5)

    # Sync Jobs Tab
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
    running_image = create_status_image((0, 200, 0), 'running')  # Green
    syncing_image = create_status_image((0, 120, 255), 'syncing')  # Blue
    error_image = create_status_image((255, 0, 0), 'error')  # Red
    config_invalid_image = create_status_image(
        (255, 200, 0), 'config_invalid')  # Orange

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
                if "error" not in current_status:
                    if current_status.get("currently_syncing"):
                        icon.icon = syncing_image
                    elif current_status.get("config_invalid"):
                        icon.icon = config_invalid_image
                    else:
                        icon.icon = running_image
                else:
                    icon.icon = error_image
                icon.update_menu()
                last_status = current_status
            time.sleep(1)

    threading.Thread(target=check_status_and_update, daemon=True).start()
    icon.run()


if __name__ == "__main__":
    run_tray()
