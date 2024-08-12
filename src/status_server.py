import os
import socket
import json
import threading
from datetime import datetime
from config import sync_jobs, last_sync_times
from scheduler import scheduler
from shared_variables import *


def start_status_server():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'

    if os.path.exists(socket_path):
        os.unlink(socket_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(1)
    server.settimeout(1)  # Set a timeout so we can check the running flag

    while True:
        try:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn,)).start()
        except socket.timeout:
            if shutting_down:
                break

    server.close()
    os.unlink(socket_path)


def handle_client(conn):
    try:
        status = generate_status_report()
        conn.sendall(status.encode())
    finally:
        conn.close()


def generate_status_report():
    current_time = datetime.now()
    status = {
        "pid": os.getpid(),
        "active_syncs": {},
        "last_check": current_time.isoformat(),
        "global_dry_run": dry_run,
        "currently_syncing": currently_syncing,
        "sync_queue_size": sync_queue.qsize(),
        "queued_paths": list(queued_paths),
        "shutting_down": shutting_down
    }

    if currently_syncing and 'current_sync_start_time' in globals():
        sync_duration = current_time - globals()['current_sync_start_time']
        status["current_sync_duration"] = str(sync_duration).split('.')[
            0]  # Remove microseconds

    for key, value in sync_jobs.items():
        local_path = value['local']
        remote_path = f"{value['rclone_remote']}:{value['remote']}"

        last_sync = last_sync_times.get(key, "Never")
        if isinstance(last_sync, datetime):
            last_sync = last_sync.isoformat()

        status["active_syncs"][key] = {
            "local_path": local_path,
            "remote_path": remote_path,
            "sync_interval": value.get('sync_interval', "Not set"),
            "last_sync": last_sync,
            "dry_run": dry_run or value.get('dry_run', False),
            "is_active": value.get('active', True),
            "is_currently_syncing": key == currently_syncing,
        }

        if key == currently_syncing and 'current_sync_start_time' in globals():
            sync_duration = current_time - globals()['current_sync_start_time']
            status["active_syncs"][key]["current_sync_duration"] = str(
                sync_duration).split('.')[0]  # Remove microseconds

    return json.dumps(status, ensure_ascii=False, indent=2)
