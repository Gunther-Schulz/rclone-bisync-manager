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

from rclone_bisync_manager.logging_utils import log_error
from rclone_bisync_manager.logging_utils import log_message
from rclone_bisync_manager import status_protocol as sp


def start_status_server(handlers=None, state=None, config=None):
    """Run the status socket server.
    handlers: optional dict of command -> callable (e.g. {'RELOAD': reload_config}).
    state: daemon runtime state (running, shutting_down, in_limbo, config_invalid, etc.).
    config: config object (_config, paths, etc.). Sync state/errors come from get_sync_state_store().
    """
    from rclone_bisync_manager.config import config as default_config
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
    server.listen(1)
    server.settimeout(1)  # Set a timeout so we can check the running flag

    while getattr(s, "running", True) or not getattr(s, "shutdown_complete", False):
        try:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, handlers, s, c)).start()
        except socket.timeout:
            continue

    server.close()
    try:
        os.unlink(socket_path)
    except OSError:
        pass


def handle_client(conn, handlers=None, state=None, config=None):
    from rclone_bisync_manager.config import config as default_config
    if handlers is None:
        handlers = {}
    s = state if state is not None else default_config
    c = config if config is not None else s
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
    except Exception as e:
        log_error(f"Error handling client request: {str(e)}")
    finally:
        conn.close()


def generate_status_report(state=None, config=None):
    """state: runtime (running, shutting_down, currently_syncing, queued_paths, in_limbo, config_invalid). config: _config, paths, hash_warnings. sync_errors from get_sync_state_store()."""
    from rclone_bisync_manager.config import config as default_config
    s = state if state is not None else default_config
    c = config if config is not None else default_config
    try:
        store = get_sync_state_store()
        c_config = getattr(c, "_config", None)
        status = {
            sp.PID: os.getpid(),
            sp.RUNNING: s.running,
            sp.SHUTTING_DOWN: s.shutting_down,
            sp.IN_LIMBO: getattr(s, "in_limbo", True),
            sp.CONFIG_INVALID: getattr(s, "config_invalid", False),
            sp.CONFIG_ERROR_MESSAGE: getattr(s, "config_error_message", None),
            sp.CURRENTLY_SYNCING: s.currently_syncing,
            sp.QUEUED_PATHS: list(s.queued_paths),
            sp.CONFIG_CHANGED_ON_DISK: getattr(c, "config_changed_on_disk", False),
            sp.CONFIG_FILE_LOCATION: str(getattr(c, "config_file", "") or ""),
            sp.LOG_FILE_LOCATION: str(c_config.log_file_path) if c_config else None,
            sp.SYNC_ERRORS: store.sync_errors
        }

        if c_config and not getattr(s, "in_limbo", True) and not getattr(s, "config_invalid", False):
            status[sp.CURRENT_CONFIG] = model_to_dict(c_config)
            status[sp.SYNC_JOBS] = {}
            hash_warnings = getattr(c, "hash_warnings", {}) or {}
            for key, value in c_config.sync_jobs.items():
                if value.active:
                    job_state = store.sync_state.get_job_state(key)
                    status[sp.SYNC_JOBS][key] = model_to_dict(value)
                    def _iso_or_none(v):
                        return v.isoformat() if v is not None and hasattr(v, "isoformat") else None
                    status[sp.SYNC_JOBS][key].update({
                        sp.LAST_SYNC: _iso_or_none(job_state["last_sync"]),
                        sp.NEXT_RUN: _iso_or_none(job_state["next_run"]),
                        sp.SYNC_STATUS: standardize_status(job_state["sync_status"]),
                        sp.RESYNC_STATUS: standardize_status(job_state["resync_status"]),
                        sp.HASH_WARNINGS: hash_warnings.get(key, False)
                    })

        return json.dumps(status, default=json_serializer, ensure_ascii=False)
    except Exception as e:
        error_message = f"Error generating status report: {str(e)}"
        log_error(error_message)
        return json.dumps({sp.STATUS: "error", sp.MESSAGE: error_message})


def model_to_dict(obj: Any) -> dict:
    return {k: v for k, v in obj.model_dump().items() if v is not None}


def json_serializer(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        if hasattr(obj, 'model_dump'):
            # For newer Pydantic versions
            return obj.model_dump()
        else:
            # For older Pydantic versions
            return obj.dict()
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
    if isinstance(status, dict):
        # If it's a dict, return the most relevant status
        # Adjust this logic based on your specific requirements
        return next((v for v in status.values() if v != "NONE"), "NONE")
    return status if status is not None else "NONE"
