import json
import os
import signal
import socket
import sys
import time
import traceback
from rclone_bisync_manager.status_server import start_status_server
from rclone_bisync_manager.logging_utils import log_message, log_error
from rclone_bisync_manager.utils import check_and_create_lock_file
from rclone_bisync_manager.sync import perform_sync_operations
from rclone_bisync_manager.sync_context import build_sync_context
from rclone_bisync_manager.config import signal_handler
from rclone_bisync_manager import status_protocol as sp
from rclone_bisync_manager.daemon_state import DaemonRuntimeState
import rclone_bisync_manager.daemon_state as state_module
from rclone_bisync_manager.runtime_paths import (
    clear_crash_log,
    get_add_sync_socket_path,
    get_lock_file_path,
    write_crash_log,
)
from rclone_bisync_manager.daemon_client import request_stop, request_status
import threading
from datetime import datetime
import fcntl
from croniter import croniter

# Injected by run_daemon_start before DaemonContext; used by daemon_main and helpers.
_daemon_config = None
_daemon_scheduler = None

# Daemon child process uses sys.exit(1) on failure so "daemon start" fails and CLI/tray see the exit code.


def _run_main_loop(state, status_thread):
    """Run the main daemon loop and graceful shutdown. Uses state_module.daemon_state, _daemon_config, _daemon_scheduler."""
    last_config_check = time.time()
    config_check_interval = 1

    while state.running:
        current_time = time.time()
        if current_time - last_config_check >= config_check_interval:
            _daemon_config.check_config_changed()
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

    shutdown_start = time.time()
    while state.currently_syncing and time.time() - shutdown_start < 60:
        log_message(f"Waiting for current sync to finish: {state.currently_syncing}")
        time.sleep(5)

    if state.currently_syncing:
        log_message(
            f"Sync operation {state.currently_syncing} did not finish within timeout. Forcing shutdown."
        )

    while not state.sync_queue.empty():
        state.sync_queue.get_nowait()
    state.queued_paths.clear()

    state.shutdown_complete = True
    log_message('Daemon shutdown complete.')
    status_thread.join(timeout=5)


def daemon_main():
    """Run loop entry (child after fork): acquire lifecycle lock, state, signals, threads, config load, main loop, shutdown."""
    print("Entering daemon_main()")
    if _daemon_config is None or _daemon_scheduler is None:
        log_error("daemon_main called without injected config/scheduler (must be started via run_daemon_start).")
        sys.exit(1)

    # --- Acquire lifecycle lock (child; parent lock was for start serialization only) ---
    lock_fd, error_message = check_and_create_lock_file()
    if error_message:
        log_error(f"Error starting daemon: {error_message}")
        print(f"Error starting daemon: {error_message}")
        sys.exit(1)

    # --- State setup ---
    state = DaemonRuntimeState()
    state.args = _daemon_config.args
    state.lock_fd = lock_fd
    state_module.daemon_state = state

    try:
        print("Daemon started in limbo state")
        log_message("Daemon started in limbo state")

        # --- Signal handlers ---
        print("Setting up signal handlers")
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        # --- Threads: status server, add-sync handler ---
        print("Starting status server thread")
        status_thread = threading.Thread(
            target=start_status_server,
            kwargs={"handlers": {"RELOAD": reload_config}, "state": state, "config": _daemon_config},
            daemon=True,
        )
        status_thread.start()

        print("Starting add-sync request handler thread")
        add_sync_thread = threading.Thread(
            target=handle_add_sync_request, daemon=True)
        add_sync_thread.start()

        # --- Config load (exit limbo on success) ---
        print("Attempting to load and validate config")
        try:
            _daemon_config.load_and_validate_config(_daemon_config.args)
            print("Configuration loaded and validated successfully")
            log_message(
                "Configuration loaded and validated successfully. Exiting limbo state.")
            state.in_limbo = False
            state.config_invalid = False
            state.config_error_message = None
            clear_crash_log()
            print("Scheduling tasks")
            _daemon_scheduler.schedule_tasks(_daemon_config._config.sync_jobs, _daemon_config._config.run_missed_jobs)
        except Exception as e:
            error_trace = traceback.format_exc()
            error_message = f"Configuration error: {str(e)}\n{error_trace}"
            print(f"Configuration error: {str(e)}")
            print(f"Full traceback:\n{error_trace}")
            log_error(f"Configuration error: {str(e)}\n{error_trace}")
            state.in_limbo = True
            state.config_invalid = True
            state.config_error_message = str(e)
            write_crash_log(error_message)  # So tray can show "Show Full Error" when daemon exits
            sys.exit(1)  # Child exit with failure code so "daemon start" fails

        # --- Main loop + graceful shutdown ---
        _run_main_loop(state, status_thread)

    except Exception as e:
        error_message = f"Daemon crashed unexpectedly: {
            str(e)}\n{traceback.format_exc()}"
        log_error(error_message)
        write_crash_log(error_message)
        sys.exit(1)  # Child exit with failure code so "daemon start" / crash is reported as failure
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


def process_sync_queue():
    state = state_module.daemon_state
    if state is None:
        return
    if not getattr(_daemon_config, "_config", None):
        return
    while not state.sync_queue.empty() and not state.shutting_down:
        key = None
        force_bisync = False
        force_resync = False
        with state.sync_lock:
            if state.currently_syncing is None:
                key, force_bisync, force_resync = state.sync_queue.get_nowait()
                state.currently_syncing = key
                state.queued_paths.discard(key)
                state.current_sync_start_time = datetime.now()
            else:
                break

        if key is not None and key not in _daemon_config._config.sync_jobs:
            log_message(f"Skipping queued job '{key}': no longer in config.")
        elif key is not None and key in _daemon_config._config.sync_jobs and not state.shutting_down:
            try:
                ctx = build_sync_context(
                    key,
                    _daemon_config,
                    force_bisync_override=force_bisync,
                    force_resync_override=force_resync,
                )
                perform_sync_operations(key, context=ctx)
                _daemon_config._last_log_position = ctx.log_state.last_log_position
            except Exception as e:
                log_error(f"Sync failed for job '{key}': {e}\n{traceback.format_exc()}")
        if key is not None:
            with state.sync_lock:
                state.currently_syncing = None
                state.current_sync_start_time = None


def check_scheduled_tasks():
    state = state_module.daemon_state
    if state is None:
        return
    if not getattr(_daemon_config, "_config", None):
        return
    while True:
        next_task = _daemon_scheduler.get_next_task()
        if next_task and not state.shutting_down:
            now = datetime.now()
            if now >= next_task.scheduled_time:
                task = _daemon_scheduler.pop_next_task()
                if task.path_key not in _daemon_config._config.sync_jobs:
                    log_message(f"Skipping scheduled task: job '{task.path_key}' no longer in config.")
                    continue
                add_to_sync_queue(task.path_key)
                job_config = _daemon_config._config.sync_jobs[task.path_key]
                cron = croniter(job_config.schedule, now)
                next_run = cron.get_next(datetime)
                _daemon_scheduler.schedule_task(task.path_key, next_run)
            else:
                break
        else:
            break


def add_to_sync_queue(key, force_bisync=False, resync=False):
    state = state_module.daemon_state
    if state is None:
        return
    if not getattr(_daemon_config, "_config", None) or key not in _daemon_config._config.sync_jobs:
        log_message(f"Skipping add_to_sync_queue: job '{key}' not in config.")
        return
    if not state.shutting_down and key not in state.queued_paths and key != state.currently_syncing:
        state.sync_queue.put_nowait((key, force_bisync, resync))
        state.queued_paths.add(key)


def stop_daemon():
    if not os.path.exists(get_lock_file_path()):
        print("Daemon is not running.")
        return
    result = request_stop()
    if result is None:
        print("Daemon is not running (no response from socket).")
        return
    if isinstance(result, dict) and result.get(sp.STATUS) == "success":
        print("Daemon is shutting down. Use 'daemon status' to check progress.")
    else:
        msg = result.get(sp.MESSAGE, result) if isinstance(result, dict) else result
        print(f"Error stopping daemon: {msg}")


def print_daemon_status():
    status_dict = request_status(timeout=5)
    if status_dict is None:
        print("Daemon is not running.")
        return
    if not isinstance(status_dict, dict):
        print("Unexpected status response from daemon.")
        return
    if status_dict.get(sp.SHUTTING_DOWN, False):
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
        conn = None
        try:
            conn, addr = server.accept()
            data = conn.recv(1024).decode('utf-8', errors='replace')
            try:
                sync_request = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                sync_request = None
            if not isinstance(sync_request, dict):
                if conn is not None:
                    try:
                        conn.sendall(b"ERROR: invalid JSON or non-object payload")
                    except (OSError, socket.error):
                        pass
                continue
            job = sync_request.get('job_key')
            if job is None:
                conn.sendall(b"ERROR: missing job_key")
                continue
            if not getattr(_daemon_config, "_config", None):
                conn.sendall(b"ERROR: config not loaded")
                continue
            force_bisync = bool(sync_request.get('force_bisync', False))
            resync = bool(sync_request.get('resync', False))

            if job in _daemon_config._config.sync_jobs:
                add_to_sync_queue(job, force_bisync=force_bisync, resync=resync)
                log_message(f"Added sync job '{job}' to queue (Force bisync: {force_bisync}, Resync: {resync})")
                conn.sendall(b"OK")
            else:
                log_error(f"Sync job '{job}' not found in configuration")
                conn.sendall(b"ERROR: Job not found")
        except socket.timeout:
            continue
        except Exception as e:
            log_error(f"Error handling add-sync request: {str(e)}")
            if conn is not None:
                try:
                    conn.sendall(b"ERROR: invalid request")
                except (OSError, socket.error):
                    pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass

    server.close()
    try:
        os.unlink(socket_path)
    except OSError:
        pass


def reload_config():
    state = state_module.daemon_state
    if state is None:
        return False
    args = state.args if state.args is not None else _daemon_config.args
    try:
        _daemon_config.load_and_validate_config(args)
        _daemon_config.reset_config_changed_flag()  # Only clear after successful load so status never briefly reports False before apply
        log_message("Config reloaded successfully.")
        _daemon_scheduler.clear_tasks()
        _daemon_scheduler.schedule_tasks(_daemon_config._config.sync_jobs, _daemon_config._config.run_missed_jobs)
        state.config_invalid = False
        state.in_limbo = False
        state.config_error_message = None
        return True
    except Exception as e:
        error_message = f"Error reloading config: {str(e)}"
        log_error(error_message)
        state.config_invalid = True
        state.in_limbo = True
        state.config_error_message = error_message
        log_message("Daemon entering limbo state due to invalid configuration.")
        return False
