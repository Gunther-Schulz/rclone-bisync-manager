import json
import socket
from status_server import start_status_server
from logging_utils import log_message, log_error
from utils import check_config_changed, parse_interval
from scheduler import scheduler
from sync import perform_sync_operations
from config import config, load_config, signal_handler
import os
import signal
import time
import threading
from datetime import datetime, timedelta


def daemon_main():
    log_message("Daemon started")

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    status_thread = threading.Thread(target=start_status_server, daemon=True)
    status_thread.start()

    # Perform initial sync for all active paths
    log_message("Starting initial sync for all active sync jobs")
    for key, value in config.sync_jobs.items():
        if value.get('active', True):
            add_to_sync_queue(key)

    while config.running:
        try:
            process_sync_queue()
            check_scheduled_tasks()
            check_and_reload_config()
            time.sleep(1)
        except Exception as e:
            log_error(f"An error occurred in the main loop: {str(e)}")
            time.sleep(1)  # Avoid tight loop in case of persistent errors

        if config.shutting_down:
            log_message(
                "Shutdown signal received, initiating graceful shutdown")
            break

    # Graceful shutdown
    log_message('Daemon shutting down...')

    # Wait for current sync to finish
    while config.currently_syncing:
        log_message(f"Waiting for current sync to finish: {
                    config.currently_syncing}")
        time.sleep(5)  # Log every 5 seconds instead of every second

    # Clear remaining queue
    while not config.sync_queue.empty():
        config.sync_queue.get_nowait()
    config.queued_paths.clear()

    config.shutdown_complete = True
    log_message('Daemon shutdown complete.')
    status_thread.join(timeout=5)


def process_sync_queue():
    while not config.sync_queue.empty() and not config.shutting_down:
        with config.sync_lock:
            if config.currently_syncing is None:
                key = config.sync_queue.get_nowait()
                config.currently_syncing = key
                config.queued_paths.remove(key)
                config.current_sync_start_time = datetime.now()
            else:
                break

        if key in config.sync_jobs and not config.shutting_down:
            perform_sync_operations(key)

        with config.sync_lock:
            config.currently_syncing = None
            config.current_sync_start_time = None


def check_scheduled_tasks():
    next_task = scheduler.get_next_task()
    if next_task and not config.shutting_down:
        now = datetime.now()
        if now >= next_task.scheduled_time:
            task = scheduler.pop_next_task()
            add_to_sync_queue(task.path_key)


def check_and_reload_config():
    if check_config_changed() and not config.shutting_down:
        reload_config()


def add_to_sync_queue(key):
    if not config.shutting_down and key not in config.queued_paths and key != config.currently_syncing:
        config.sync_queue.put_nowait(key)
        config.queued_paths.add(key)


def reload_config():
    load_config()
    log_message("Config reloaded.")

    scheduler.clear_tasks()
    for key, value in config.sync_jobs.items():
        if value.get('active', True):
            interval = value.get('interval', '1d')
            interval = parse_interval(interval)
            scheduler.schedule_task(
                key, datetime.now() + timedelta(seconds=interval))


def stop_daemon():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    if os.path.exists(socket_path):
        try:
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
