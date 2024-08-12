import os
import socket
import json
import threading
from datetime import datetime
from config import sync_jobs, last_sync_times


def status_server():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'

    if os.path.exists(socket_path):
        os.remove(socket_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(1)

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn,)).start()


def handle_client(conn):
    try:
        status = get_status()
        conn.sendall(json.dumps(status).encode())
    finally:
        conn.close()


def get_status():
    from daemon import running, shutting_down, shutdown_complete, currently_syncing, sync_queue
    status = {
        "pid": os.getpid(),
        "running": running,
        "shutting_down": shutting_down,
        "shutdown_complete": shutdown_complete,
        "currently_syncing": currently_syncing,
        "sync_queue": sync_queue,
        "last_sync_times": {k: v.isoformat() for k, v in last_sync_times.items()},
        "sync_jobs": {}
    }

    for key, value in sync_jobs.items():
        status["sync_jobs"][key] = {
            "active": value.get("active", True),
            "local_path": value["local"],
            "remote_path": f"{value['rclone_remote']}:{value['remote']}",
            "sync_interval": value["sync_interval"]
        }

    return status
