import os
import socket
import json
import threading
from config import config
from scheduler import scheduler
from sync import read_status


def start_status_server():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'

    if os.path.exists(socket_path):
        os.unlink(socket_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(1)
    server.settimeout(1)  # Set a timeout so we can check the running flag

    while config.running or not config.shutdown_complete:
        try:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn,)).start()
        except socket.timeout:
            continue

    server.close()
    os.unlink(socket_path)


def handle_client(conn):
    try:
        data = conn.recv(1024).decode()
        if data == "RELOAD":
            from daemon_functions import reload_config
            success = reload_config()
            if success:
                conn.sendall(b"Configuration reloaded successfully")
            else:
                conn.sendall(
                    b"Error reloading configuration. Daemon is in limbo state. Check logs for details.")
        elif data == "STOP":
            config.running = False
            config.shutting_down = True
            conn.sendall(b"Shutdown signal sent to daemon")
        elif data == "STATUS":
            status = generate_status_report()
            conn.sendall(status.encode())
        else:
            conn.sendall(b"Invalid command")
    except Exception as e:
        conn.sendall(f"Error: {str(e)}".encode())
    finally:
        conn.close()


def generate_status_report():
    status = {
        "pid": os.getpid(),
        "running": config.running,
        "shutting_down": config.shutting_down,
        "config_invalid": config.config_invalid,
        "currently_syncing": config.currently_syncing,
        "queued_paths": list(config.queued_paths),
        "sync_jobs": {}
    }

    for key, value in config._config.sync_jobs.items():
        if value.active:
            sync_status, resync_status = read_status(key)
            last_sync = config.last_sync_times.get(key)
            next_task = scheduler.get_next_task()
            next_run = next_task.scheduled_time if next_task and next_task.path_key == key else None

            status["sync_jobs"][key] = {
                "last_sync": last_sync.isoformat() if last_sync else None,
                "next_run": next_run.isoformat() if next_run else None,
                "sync_status": sync_status,
                "resync_status": resync_status
            }

    return json.dumps(status)
