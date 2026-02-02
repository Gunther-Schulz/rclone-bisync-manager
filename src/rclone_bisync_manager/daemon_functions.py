import json
import socket
import traceback
from rclone_bisync_manager.status_server import start_status_server
from rclone_bisync_manager.logging_utils import log_message, log_error
from rclone_bisync_manager.utils import check_and_create_lock_file
from rclone_bisync_manager.scheduler import scheduler
from rclone_bisync_manager.sync import perform_sync_operations
from rclone_bisync_manager.config import config, signal_handler
from rclone_bisync_manager.daemon_state import DaemonRuntimeState
import rclone_bisync_manager.daemon_state as state_module
from rclone_bisync_manager.runtime_paths import (
    get_add_sync_socket_path,
    get_crash_log_path,
    get_lock_file_path,
)
from rclone_bisync_manager.daemon_client import request_stop, request_status
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

    state = DaemonRuntimeState()
    state.args = config.args
    state.lock_fd = lock_fd
    state_module.daemon_state = state

    try:
        print("Daemon started in limbo state")
        log_message("Daemon started in limbo state")

        print("Setting up signal handlers")
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        print("Starting status server thread")
        status_thread = threading.Thread(
            target=start_status_server,
            kwargs={"handlers": {"RELOAD": reload_config}, "state": state, "config": config},
            daemon=True,
        )
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
            state.in_limbo = False
            state.config_invalid = False
            state.config_error_message = None
            print("Scheduling tasks")
            scheduler.schedule_tasks()
        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"Configuration error: {str(e)}")
            print(f"Full traceback:\n{error_trace}")
            log_error(f"Configuration error: {str(e)}\n{error_trace}")
            state.in_limbo = True
            state.config_invalid = True
            state.config_error_message = str(e)
            return  # Exit the daemon_main function if there's a config error

        print("Entering main daemon loop")
        last_config_check = time.time()
        config_check_interval = 1

        while state.running:
            current_time = time.time()
            if current_time - last_config_check >= config_check_interval:
                config.check_config_changed()
                last_config_check = current_time

            if not state.in_limbo and not state.config_invalid:
                process_sync_queue()
                check_scheduled_tasks()

            time.sleep(1)
            if state.shutting_down:
                print("Shutdown signal received, initiating graceful shutdown")
                log_message(
                    "Shutdown signal received, initiating graceful shutdown")
                break

        print("Exiting main daemon loop")

        # Graceful shutdown
        log_message('Daemon shutting down...')

        # Wait for current sync to finish with a timeout
        shutdown_start = time.time()
        while state.currently_syncing and time.time() - shutdown_start < 60:  # 60 seconds timeout
            log_message(f"Waiting for current sync to finish: {
                        state.currently_syncing}")
            time.sleep(5)

        if state.currently_syncing:
            log_message(f"Sync operation {
                        state.currently_syncing} did not finish within timeout. Forcing shutdown.")

        # Clear remaining queue
        while not state.sync_queue.empty():
            state.sync_queue.get_nowait()
        state.queued_paths.clear()

        state.shutdown_complete = True
        log_message('Daemon shutdown complete.')
        status_thread.join(timeout=5)

    except Exception as e:
        error_message = f"Daemon crashed unexpectedly: {
            str(e)}\n{traceback.format_exc()}"
        log_error(error_message)
        write_crash_log(error_message)
    finally:
        state_module.daemon_state = None
        if lock_fd is not None:
            try:
                fcntl.lockf(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            except IOError:
                pass  # Ignore errors during shutdown
            try:
                os.unlink(get_lock_file_path())
            except OSError:
                pass  # Ignore if the file is already gone


def write_crash_log(error_message):
    crash_log_path = get_crash_log_path()
    with open(crash_log_path, 'w') as f:
        f.write(error_message)


def process_sync_queue():
    state = state_module.daemon_state
    if state is None:
        return
    while not state.sync_queue.empty() and not state.shutting_down:
        with state.sync_lock:
            if state.currently_syncing is None:
                key, force_bisync, force_resync = state.sync_queue.get_nowait()
                state.currently_syncing = key
                state.queued_paths.remove(key)
                state.current_sync_start_time = datetime.now()
            else:
                break

        if key in config._config.sync_jobs and not state.shutting_down:
            perform_sync_operations(key, force_bisync, force_resync)

        with state.sync_lock:
            state.currently_syncing = None
            state.current_sync_start_time = None


def check_scheduled_tasks():
    state = state_module.daemon_state
    if state is None:
        return
    while True:
        next_task = scheduler.get_next_task()
        if next_task and not state.shutting_down:
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


def add_to_sync_queue(key, force_bisync=False, resync=False):
    state = state_module.daemon_state
    if state is None:
        return
    if not state.shutting_down and key not in state.queued_paths and key != state.currently_syncing:
        config._config.sync_jobs[key].force_operation = force_bisync
        config._config.sync_jobs[key].force_resync = resync
        state.sync_queue.put_nowait((key, force_bisync, resync))
        state.queued_paths.add(key)


def stop_daemon():
    if not os.path.exists(get_lock_file_path()):
        print("Daemon is not running.")
        return
    result = request_stop()
    if result and result.get("status") == "success":
        print("Daemon is shutting down. Use 'daemon status' to check progress.")
    elif result:
        print(f"Error stopping daemon: {result.get('message', result)}")


def print_daemon_status():
    status_dict = request_status(timeout=5)
    if status_dict is None:
        print("Daemon is not running.")
        return
    if status_dict.get("shutting_down", False):
        print("Daemon is shutting down. Current status:")
    print(json.dumps(status_dict, ensure_ascii=False, indent=2))


def handle_add_sync_request():
    socket_path = get_add_sync_socket_path()
    if os.path.exists(socket_path):
        os.unlink(socket_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(1)
    server.settimeout(1)

    state = state_module.daemon_state
    while state is not None and state.running and not state.shutting_down:
        try:
            conn, addr = server.accept()
            data = conn.recv(1024).decode()
            sync_request = json.loads(data)
            job = sync_request['job_key']
            force_bisync = sync_request.get('force_bisync', False)
            resync = sync_request.get('resync', False)

            if job in config._config.sync_jobs:
                config._config.sync_jobs[job].force_operation = force_bisync
                config._config.sync_jobs[job].force_resync = resync
                add_to_sync_queue(
                    job, force_bisync=force_bisync, resync=resync)
                log_message(f"Added sync job '{job}' to queue (Force bisync: {
                            force_bisync}, Resync: {resync})")
                conn.sendall(b"OK")
            else:
                log_error(f"Sync job '{job}' not found in configuration")
                conn.sendall(b"ERROR: Job not found")
            conn.close()
        except socket.timeout:
            continue
        except Exception as e:
            log_error(f"Error handling add-sync request: {str(e)}")

    server.close()
    os.unlink(socket_path)


def reload_config():
    state = state_module.daemon_state
    if state is None:
        return False
    args = state.args if state.args is not None else config.args
    config.reset_config_changed_flag()
    try:
        config.load_and_validate_config(args)
        log_message("Config reloaded successfully.")
        scheduler.clear_tasks()
        scheduler.schedule_tasks()
        state.config_invalid = False
        state.in_limbo = False
        state.config_error_message = None
        return True
    except (ValueError, FileNotFoundError) as e:
        error_message = f"Error reloading config: {str(e)}"
        log_error(error_message)
        state.config_invalid = True
        state.in_limbo = True
        state.config_error_message = error_message
        log_message("Daemon entering limbo state due to invalid configuration.")
        return False
