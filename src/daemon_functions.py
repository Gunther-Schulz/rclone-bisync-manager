import json
import socket
from status_server import start_status_server
from logging_utils import log_message, log_error
from utils import check_and_create_lock_file
from scheduler import scheduler
from sync import perform_sync_operations
from config import config, signal_handler
import os
import signal
import time
import threading
from datetime import datetime, timedelta
import fcntl
from croniter import croniter
from queue import Queue


def daemon_main():
    lock_fd, error_message = check_and_create_lock_file()
    if error_message:
        log_error(f"Error starting daemon: {error_message}")
        return

    try:
        # This will now validate the configuration
        config.load_and_validate_config(config.args)
    except ValueError as e:
        log_error(f"Configuration error: {str(e)}")
        return
    except FileNotFoundError:
        log_error(
            "Configuration file not found. Please create a valid configuration file.")
        return

    try:
        log_message("Daemon started")

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        status_thread = threading.Thread(
            target=start_status_server, daemon=True)
        status_thread.start()

        add_sync_thread = threading.Thread(
            target=handle_add_sync_request, daemon=True)
        add_sync_thread.start()

        if config._config.run_initial_sync_on_startup:
            log_message("Starting initial sync for all active sync jobs")
            for key, value in config._config.sync_jobs.items():
                if value.active:
                    add_to_sync_queue(key)
        else:
            log_message("Skipping initial sync as per configuration")

        limbo_message_logged = False
        while config.running:
            if config.config_invalid:
                if not limbo_message_logged:
                    log_message(
                        "Daemon in limbo state due to invalid configuration. Waiting for valid config...")
                    limbo_message_logged = True
                time.sleep(5)  # Sleep for 5 seconds when in limbo state
                continue
            else:
                limbo_message_logged = False  # Reset the flag when config is valid

            process_sync_queue()
            check_scheduled_tasks()
            time.sleep(1)
            if config.shutting_down:
                log_message(
                    "Shutdown signal received, initiating graceful shutdown")
                break

        # Graceful shutdown
        log_message('Daemon shutting down...')

        # Wait for current sync to finish with a timeout
        shutdown_start = time.time()
        while config.currently_syncing and time.time() - shutdown_start < 60:  # 60 seconds timeout
            log_message(f"Waiting for current sync to finish: {
                        config.currently_syncing}")
            time.sleep(5)

        if config.currently_syncing:
            log_message(f"Sync operation {
                        config.currently_syncing} did not finish within timeout. Forcing shutdown.")

        # Clear remaining queue
        while not config.sync_queue.empty():
            config.sync_queue.get_nowait()
        config.queued_paths.clear()

        config.shutdown_complete = True
        log_message('Daemon shutdown complete.')
        status_thread.join(timeout=5)

    finally:
        if lock_fd is not None:
            fcntl.lockf(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            os.unlink(config.LOCK_FILE_PATH)


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

        if key in config._config.sync_jobs and not config.shutting_down:
            perform_sync_operations(key)

        with config.sync_lock:
            config.currently_syncing = None
            config.current_sync_start_time = None


def check_scheduled_tasks():
    while True:
        next_task = scheduler.get_next_task()
        if next_task and not config.shutting_down:
            now = datetime.now()
            if now >= next_task.scheduled_time:
                task = scheduler.pop_next_task()
                add_to_sync_queue(task.path_key)
                # Reschedule the task
                job_config = config._config.sync_jobs[task.path_key]
                cron = croniter(job_config.schedule, now)
                next_run = cron.get_next(datetime)
                scheduler.schedule_task(task.path_key, next_run)
            else:
                break
        else:
            break


def add_to_sync_queue(key):
    if not config.shutting_down and key not in config.queued_paths and key != config.currently_syncing:
        config.sync_queue.put_nowait(key)
        config.queued_paths.add(key)


def reload_config():
    try:
        config.load_and_validate_config(config.args)
        new_sync_jobs = set(config._config.sync_jobs.keys())

        with config.sync_lock:
            # Remove jobs from the queue that are no longer in the config
            config.queued_paths = config.queued_paths.intersection(
                new_sync_jobs)
            new_queue = Queue()
            while not config.sync_queue.empty():
                job = config.sync_queue.get()
                if job in new_sync_jobs:
                    new_queue.put(job)
            config.sync_queue = new_queue

        log_message("Config reloaded successfully.")
        scheduler.clear_tasks()
        scheduler.schedule_tasks()
        config.config_invalid = False
        return True
    except (ValueError, FileNotFoundError) as e:
        error_message = f"Error reloading config: {str(e)}"
        log_error(error_message)
        config.config_invalid = True
        config.config_error_message = error_message
        log_message("Daemon entering limbo state due to invalid configuration.")
        return False


def stop_daemon():
    if not os.path.exists(config.LOCK_FILE_PATH):
        print("Daemon is not running.")
        return

    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect('/tmp/rclone_bisync_manager_status.sock')
        client.sendall(b"STOP")
        response = client.recv(1024).decode()
        client.close()
        print("Daemon is shutting down. Use 'daemon status' to check progress.")
    except Exception as e:
        print(f"Error stopping daemon: {e}")


def print_daemon_status():
    socket_path = '/tmp/rclone_bisync_manager_status.sock'
    if not os.path.exists(socket_path):
        print("Daemon is not running.")
        return

    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(5)  # Set a 5-second timeout
        client.connect(socket_path)
        client.sendall(b"STATUS")
        status = client.recv(4096).decode()
        client.close()

        if status.startswith("Error:"):
            print(f"Error getting daemon status: {status}")
        else:
            status_dict = json.loads(status)
            if status_dict.get("shutting_down", False):
                print("Daemon is shutting down. Current status:")
            print(json.dumps(status_dict, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Error communicating with daemon: {e}")


def handle_add_sync_request():
    socket_path = '/tmp/rclone_bisync_manager_add_sync.sock'
    if os.path.exists(socket_path):
        os.unlink(socket_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(1)
    server.settimeout(1)

    while config.running and not config.shutting_down:
        try:
            conn, addr = server.accept()
            data = conn.recv(1024).decode()
            sync_jobs = json.loads(data)
            for job in sync_jobs:
                if job in config._config.sync_jobs:
                    add_to_sync_queue(job)
                    log_message(f"Added sync job '{job}' to queue")
                else:
                    log_error(f"Sync job '{job}' not found in configuration")
            conn.sendall(b"OK")
            conn.close()
        except socket.timeout:
            continue
        except Exception as e:
            log_error(f"Error handling add-sync request: {str(e)}")

    server.close()
    os.unlink(socket_path)
