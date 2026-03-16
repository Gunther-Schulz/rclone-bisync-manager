import os
import socket
import json
import threading
from pathlib import Path

from rclone_bisync_manager.runtime_paths import get_status_socket_path

from pydantic import BaseModel
from rclone_bisync_manager.config import get_config_schema
from rclone_bisync_manager.sync_state_store import get_sync_state_store
from typing import Any
from datetime import datetime, date

from rclone_bisync_manager.logging_utils import log_error, log_message
from rclone_bisync_manager import status_protocol as sp
from rclone_bisync_manager.status_protocol import StatusResponse


def start_status_server(handlers=None, state=None, config=None, max_connections=10):
    """Run the status socket server.
    handlers: optional dict of command -> callable (e.g. {'RELOAD': reload_config}).
    state: daemon runtime state (running, shutting_down, in_limbo, config_invalid, etc.).
    config: config object (_config, paths, etc.). Sync state/errors come from get_sync_state_store().
    max_connections: maximum concurrent connections (default: 10).
    """
    from rclone_bisync_manager.config import get_config
    default_config = get_config()
    socket_path = get_status_socket_path()
    if handlers is None:
        handlers = {}
    s = state if state is not None else default_config
    c = config if config is not None else s

    if os.path.exists(socket_path):
        try:
            os.unlink(socket_path)
        except OSError:
            pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(max_connections)
    server.settimeout(1)  # Set timeout to check running flag and handle connections

    # Track active connections for connection limiting
    active_connections = set()
    connections_lock = threading.Lock()

    while getattr(s, "running", True) or not getattr(s, "shutdown_complete", False):
        try:
            conn, addr = server.accept()
            with connections_lock:
                if len(active_connections) >= max_connections:
                    # Reject if at max connections
                    log_message(f"Status server: rejected connection (max {max_connections} connections)")
                    try:
                        conn.sendall(json.dumps({
                            sp.STATUS: "error",
                            sp.MESSAGE: f"Server busy, max {max_connections} connections"
                        }).encode())
                    except OSError:
                        pass
                    conn.close()
                    continue
                active_connections.add(conn)
                threading.Thread(
                    target=handle_client,
                    args=(conn, handlers, s, c, connections_lock, active_connections),
                    daemon=True
                ).start()
        except socket.timeout:
            # Timeout allows us to check running flag and cleanup
            continue

    # Cleanup remaining connections
    with connections_lock:
        for conn in active_connections:
            try:
                conn.close()
            except OSError:
                pass
        active_connections.clear()

    server.close()
    try:
        os.unlink(socket_path)
    except OSError:
        pass


def handle_client(conn, handlers=None, state=None, config=None, connections_lock=None, active_connections=None):
    """Handle a single client connection with connection management and timeout."""
    from rclone_bisync_manager.config import get_config
    default_config = get_config()
    if handlers is None:
        handlers = {}
    s = state if state is not None else default_config
    c = config if config is not None else s

    # Set connection timeout (30 seconds) to prevent hanging
    conn.settimeout(30)

    try:
        data = conn.recv(4096).decode('utf-8', errors='replace').strip()

        if data == "RELOAD":
            if "RELOAD" in handlers:
                success = handlers["RELOAD"]()
            else:
                success = False
            response = json.dumps({
                sp.STATUS: "success" if success else "error",
                sp.MESSAGE: "Configuration reloaded successfully" if success else f"Error reloading configuration. Daemon is in limbo state. Error: {getattr(s, 'config_error_message', None) or 'unknown'}"
            })
        elif data == "STOP":
            s.running = False
            s.shutting_down = True
            response = json.dumps({
                sp.STATUS: "success",
                sp.MESSAGE: "Shutdown signal sent to daemon"
            })
        elif data == "STATUS":
            response = generate_status_report(s, c)
        elif data == "GET_CONFIG":
            response = generate_config_report()
        else:
            response = json.dumps({
                sp.STATUS: "error",
                sp.MESSAGE: "Invalid command"
            })

        conn.sendall(response.encode())
    except socket.timeout:
        log_message(f"Status server: client connection timeout")
        response = json.dumps({sp.STATUS: "error", sp.MESSAGE: "Request timeout"})
        try:
            conn.sendall(response.encode())
        except OSError:
            pass
    except Exception as e:
        log_error(f"Error handling client request: {str(e)}")
        try:
            conn.sendall(json.dumps({sp.STATUS: "error", sp.MESSAGE: str(e)}).encode())
        except OSError:
            pass
    finally:
        conn.close()
        # Remove from active connections if tracking
        if connections_lock and active_connections:
            with connections_lock:
                if conn in active_connections:
                    active_connections.remove(conn)


def _get_version():
    try:
        from importlib.metadata import version
        return version("rclone-bisync-manager")
    except Exception:
        return "unknown"


def generate_status_report(state=None, config=None):
    """state: runtime (running, shutting_down, currently_syncing, queued_paths, in_limbo, config_invalid). config: _config, paths, hash_warnings. sync_errors from get_sync_state_store().
    IMPORTANT: This function returns a lightweight status response for efficient polling.
    Full config is available via GET_CONFIG command. Runtime fields only are included here."""
    from rclone_bisync_manager.config import get_config
    default_config = get_config()
    s = state if state is not None else default_config
    c = config if config is not None else default_config
    try:
        store = get_sync_state_store()
        c_config = getattr(c, "_config", None)
        status: StatusResponse = {
            sp.VERSION: _get_version(),
            sp.PID: os.getpid(),
            sp.RUNNING: getattr(s, "running", False),
            sp.SHUTTING_DOWN: getattr(s, "shutting_down", False),
            sp.IN_LIMBO: getattr(s, "in_limbo", True),
            sp.CONFIG_INVALID: getattr(s, "config_invalid", False),
            sp.CONFIG_ERROR_MESSAGE: getattr(s, "config_error_message", None),
            sp.CURRENTLY_SYNCING: getattr(s, "currently_syncing", None),
            sp.QUEUED_PATHS: list(getattr(s, "queued_paths", [])),
            sp.CONFIG_CHANGED_ON_DISK: getattr(c, "config_changed_on_disk", False),
            sp.CONFIG_FILE_LOCATION: str(getattr(c, "config_file", "") or ""),
            sp.LOG_FILE_LOCATION: str(c_config.log_file_path) if c_config else None,
            sp.SYNC_ERRORS: store.sync_errors
        }

        # Only include job runtime state, not full job definitions (for performance)
        def _iso_or_none(v):
            return v.isoformat() if v is not None and hasattr(v, "isoformat") else None

        if c_config and not getattr(s, "in_limbo", True) and not getattr(s, "config_invalid", False):
            status[sp.SYNC_JOBS] = {}
            hash_warnings = getattr(c, "hash_warnings", {}) or {}
            for key, value in c_config.sync_jobs.items():
                if value.active:
                    job_state = store.sync_state.get_job_state(key)
                    status[sp.SYNC_JOBS][key] = {
                        sp.LAST_SYNC: _iso_or_none(job_state["last_sync"]),
                        sp.NEXT_RUN: _iso_or_none(job_state["next_run"]),
                        sp.SYNC_STATUS: standardize_status(job_state["sync_status"]),
                        sp.RESYNC_STATUS: standardize_status(job_state["resync_status"]),
                        sp.HASH_WARNINGS: hash_warnings.get(key, False)
                    }

        return json.dumps(status, default=json_serializer, ensure_ascii=False)
    except Exception as e:
        error_message = f"Error generating status report: {str(e)}"
        log_error(error_message)
        return json.dumps({sp.STATUS: "error", sp.MESSAGE: error_message})


def model_to_dict(obj: Any) -> dict:
    return {k: v for k, v in obj.model_dump().items() if v is not None}


def json_serializer(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, Path):
        return str(obj)
    elif isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, dict):
        return {k: json_serializer(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [json_serializer(v) for v in obj]
    return str(obj)  # Convert any other types to strings


def generate_config_report():
    try:
        config_data = {
            "config_schema": get_config_schema()
        }
        return json.dumps(config_data, default=json_serializer, ensure_ascii=False)
    except Exception as e:
        error_message = f"Error generating config report: {str(e)}"
        log_error(error_message)
        return json.dumps({sp.STATUS: "error", sp.MESSAGE: error_message})


def standardize_status(status):
    """Normalize per-job sync/resync status for JSON. Expects str or dict; returns str."""
    if status is None:
        return "NONE"
    if isinstance(status, str):
        return status
    if isinstance(status, dict):
        return next((v for v in status.values() if v != "NONE"), "NONE")
    return "NONE"
