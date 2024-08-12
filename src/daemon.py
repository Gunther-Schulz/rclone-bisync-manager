import os
import signal
import time
import threading
from datetime import datetime, timedelta
from config import sync_jobs, last_sync_times
from sync import perform_sync_operations
from scheduler import scheduler, SyncTask
from utils import check_config_changed
from logging_utils import log_message, log_error
from status_server import status_server

running = True
shutting_down = False
shutdown_complete = False
currently_syncing = None
sync_queue = []
queued_paths = set()


def signal_handler(signum, frame):
    global running, shutting_down
    running = False
    shutting_down = True
    log_message('SIGINT or SIGTERM received. Initiating graceful shutdown.')


def daemon_main():
    global running, shutting_down, shutdown_complete, currently_syncing, queued_paths

    log_message("Daemon started")

    status_thread = threading.Thread(target=status_server, daemon=True)
    status_thread.start()

    # Perform initial sync for all active paths
    log_message("Starting initial sync for all active sync jobs")
    for key, value in sync_jobs.items():
        if value.get('active', True):
            add_to_sync_queue(key)

    while running and not shutting_down:
        try:
            # Process the sync queue
            while sync_queue and not shutting_down:
                key = sync_queue.pop(0)
                queued_paths.remove(key)
                currently_syncing = key
                perform_sync_operations(key)
                currently_syncing = None

            # Check for scheduled tasks
            next_task = scheduler.get_next_task()
            if next_task and not shutting_down:
                now = datetime.now()
                if now >= next_task.scheduled_time:
                    task = scheduler.pop_next_task()
                    add_to_sync_queue(task.path_key)
                else:
                    # Sleep until the next task or for a maximum of 1 second
                    sleep_time = min(
                        (next_task.scheduled_time - now).total_seconds(), 1)
                    time.sleep(sleep_time)
            else:
                time.sleep(1)

            if check_config_changed() and not shutting_down:
                from config import load_config
                load_config()

        except Exception as e:
            log_error(f"An error occurred in the main loop: {str(e)}")
            time.sleep(1)  # Avoid tight loop in case of persistent errors

    # Graceful shutdown
    log_message('Daemon shutting down...')

    # Wait for current sync to finish
    while currently_syncing:
        time.sleep(1)

    # Clear remaining queue
    sync_queue.clear()
    queued_paths.clear()

    shutdown_complete = True
    log_message('Daemon shutdown complete.')
    status_thread.join(timeout=5)


def add_to_sync_queue(key):
    global shutting_down
    if not shutting_down and key not in queued_paths and key != currently_syncing:
        sync_queue.append(key)
        queued_paths.add(key)


def stop_daemon():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    if os.path.exists(socket_path):
        try:
            import socket
            import json
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(socket_path)
            status = json.loads(client.recv(4096).decode())
            client.close()

            if 'pid' in status:
                os.kill(status['pid'], signal.SIGTERM)
                print(f"Sent SIGTERM to daemon (PID: {status['pid']})")
                print("Daemon is shutting down. Use 'daemon status' to check progress.")
                log_message("Daemon stop request received. Shutting down.")
            else:
                print("Unable to determine daemon PID from status")
        except Exception as e:
            print(f"Error stopping daemon: {e}")
    else:
        print("Status socket not found. Daemon may not be running.")


def print_daemon_status():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    if os.path.exists(socket_path):
        try:
            import socket
            import json
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(socket_path)
            status = json.loads(client.recv(4096).decode())
            client.close()

            if status.get("shutting_down", False):
                print("Daemon is shutting down. Current status:")
            print(json.dumps(status, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"Error getting daemon status: {e}")
    else:
        print("Daemon is not running.")
