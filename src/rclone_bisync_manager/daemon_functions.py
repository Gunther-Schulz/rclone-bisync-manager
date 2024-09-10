import json
import socket
import traceback
from rclone_bisync_manager.status_server import start_status_server
from rclone_bisync_manager.logging_utils import log_message, log_error
from rclone_bisync_manager.utils import check_and_create_lock_file
from rclone_bisync_manager.scheduler import scheduler
from rclone_bisync_manager.sync import perform_sync_operations
from rclone_bisync_manager.config import config, signal_handler
import os
import signal
import time
import threading
from datetime import datetime, timedelta
import fcntl
from croniter import croniter
from queue import Queue


def daemon_main():
    print("Entering daemon_main()")
    lock_fd, error_message = check_and_create_lock_file()
    if error_message:
        log_error(f"Error starting daemon: {error_message}")
        print(f"Error starting daemon: {error_message}")
        return

    try:
        print("Daemon started in limbo state")
        log_message("Daemon started in limbo state")

        print("Setting up signal handlers")
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        print("Starting status server thread")
        status_thread = threading.Thread(
            target=start_status_server, daemon=True)
        status_thread.start()

        print("Starting add-sync request handler thread")
        add_sync_thread = threading.Thread(
            target=handle_add_sync_request, daemon=True)
        add_sync_thread.start()

        print("Attempting to load and validate config")
        try:
            config.load_and_validate_config(config.args)
            print("Configuration loaded and validated successfully")
            log_message(
                "Configuration loaded and validated successfully. Exiting limbo state.")
            config.in_limbo = False
            print("Scheduling tasks")
            scheduler.schedule_tasks()
        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"Configuration error: {str(e)}")
            print(f"Full traceback:\n{error_trace}")
            log_error(f"Configuration error: {str(e)}\n{error_trace}")
            config.in_limbo = True
            config.config_invalid = True
            config.config_error_message = str(e)
            return  # Exit the daemon_main function if there's a config error

        print("Entering main daemon loop")
        last_config_check = time.time()
        config_check_interval = 1

        while config.running:
            current_time = time.time()
            if current_time - last_config_check >= config_check_interval:
                config.check_config_changed()
                last_config_check = current_time

            if not config.in_limbo and not config.config_invalid:
                process_sync_queue()
                check_scheduled_tasks()

            time.sleep(1)
            if config.shutting_down:
                print("Shutdown signal received, initiating graceful shutdown")
                log_message(
                    "Shutdown signal received, initiating graceful shutdown")
                break

        print("Exiting main daemon loop")

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

    except Exception as e:
        error_message = f"Daemon crashed unexpectedly: {
            str(e)}\n{traceback.format_exc()}"
        log_error(error_message)
        write_crash_log(error_message)
    finally:
        if lock_fd is not None:
            try:
                fcntl.lockf(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            except IOError:
                pass  # Ignore errors during shutdown
            try:
                os.unlink(config.LOCK_FILE_PATH)
            except OSError:
                pass  # Ignore if the file is already gone


def write_crash_log(error_message):
    crash_log_path = '/tmp/rclone_bisync_manager_crash.log'
    with open(crash_log_path, 'w') as f:
        f.write(error_message)


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


def add_to_sync_queue(key, force_bisync=False):
    if not config.shutting_down and key not in config.queued_paths and key != config.currently_syncing:
        config._config.sync_jobs[key].force_operation = force_bisync
        config.sync_queue.put_nowait(key)
        config.queued_paths.add(key)


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

        chunks = []
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        response = b''.join(chunks).decode()
        client.close()

        if not response:
            print("Error: No response received from daemon.")
            return

        try:
            status_dict = json.loads(response)
            if status_dict.get("shutting_down", False):
                print("Daemon is shutting down. Current status:")
            print(json.dumps(status_dict, ensure_ascii=False, indent=2))
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            print("Raw status data:")
            print(response)
    except Exception as e:
        print(f"Error communicating with daemon: {e}")
        print("Traceback:")
        print(traceback.format_exc())


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
            sync_request = json.loads(data)
            job = sync_request['job_key']
            force_bisync = sync_request.get('force_bisync', False)

            if job in config._config.sync_jobs:
                add_to_sync_queue(job, force_bisync)
                log_message(f"Added sync job '{
                            job}' to queue (Force bisync: {force_bisync})")
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


def reload_config():
    config.reset_config_changed_flag()
    try:
        config.load_and_validate_config(config.args)
        log_message("Config reloaded successfully.")
        scheduler.clear_tasks()
        scheduler.schedule_tasks()
        config.config_invalid = False
        config.in_limbo = False
        return True
    except (ValueError, FileNotFoundError) as e:
        error_message = f"Error reloading config: {str(e)}"
        log_error(error_message)
        config.config_invalid = True
        config.in_limbo = True
        config.config_error_message = error_message
        log_message("Daemon entering limbo state due to invalid configuration.")
        return False
