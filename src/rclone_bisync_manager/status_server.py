import os
import socket
import json
import threading
from pathlib import Path

from rclone_bisync_manager.runtime_paths import get_status_socket_path

from pydantic import BaseModel
from rclone_bisync_manager.config import sync_state, get_config_schema
from typing import Any
from datetime import datetime, date

from rclone_bisync_manager.logging_utils import log_error
from rclone_bisync_manager.logging_utils import log_message


def start_status_server(handlers=None, state=None, config=None):
    """Run the status socket server.
    handlers: optional dict of command -> callable (e.g. {'RELOAD': reload_config}).
    state: daemon runtime state (running, shutting_down, sync_queue, etc.).
    config: config object (in_limbo, _config, sync_errors, etc.). Required when state is DaemonRuntimeState.
    """
    from rclone_bisync_manager.config import config as default_config
    socket_path = get_status_socket_path()
    if handlers is None:
        handlers = {}
    s = state if state is not None else default_config
    c = config if config is not None else s

    if os.path.exists(socket_path):
        os.unlink(socket_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(1)
    server.settimeout(1)  # Set a timeout so we can check the running flag

    while s.running or not s.shutdown_complete:
        try:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, handlers, s, c)).start()
        except socket.timeout:
            continue

    server.close()
    os.unlink(socket_path)


def handle_client(conn, handlers=None, state=None, config=None):
    from rclone_bisync_manager.config import config as default_config
    if handlers is None:
        handlers = {}
    s = state if state is not None else default_config
    c = config if config is not None else s
    try:
        data = conn.recv(4096).decode().strip()

        if data == "RELOAD":
            if "RELOAD" in handlers:
                success = handlers["RELOAD"]()
            else:
                success = False
            response = json.dumps({
                "status": "success" if success else "error",
                "message": "Configuration reloaded successfully" if success else f"Error reloading configuration. Daemon is in limbo state. Error: {getattr(c, 'config_error_message', None) or 'unknown'}"
            })
        elif data == "STOP":
            s.running = False
            s.shutting_down = True
            response = json.dumps({
                "status": "success",
                "message": "Shutdown signal sent to daemon"
            })
        elif data == "STATUS":
            response = generate_status_report(s, c)
        elif data == "GET_CONFIG":
            response = generate_config_report()
        else:
            response = json.dumps({
                "status": "error",
                "message": "Invalid command"
            })

        conn.sendall(response.encode())
    except Exception as e:
        log_error(f"Error handling client request: {str(e)}")
    finally:
        conn.close()


def generate_status_report(state=None, config=None):
    """state: runtime (running, shutting_down, currently_syncing, queued_paths). config: in_limbo, _config, sync_errors, etc."""
    from rclone_bisync_manager.config import config as default_config
    s = state if state is not None else default_config
    c = config if config is not None else default_config
    try:
        status = {
            "pid": os.getpid(),
            "running": s.running,
            "shutting_down": s.shutting_down,
            "in_limbo": c.in_limbo,
            "config_invalid": c.config_invalid,
            "config_error_message": getattr(c, "config_error_message", None),
            "currently_syncing": s.currently_syncing,
            "queued_paths": list(s.queued_paths),
            "config_changed_on_disk": c.config_changed_on_disk,
            "config_file_location": str(c.config_file),
            "log_file_location": str(c._config.log_file_path) if c._config else None,
            "sync_errors": c.sync_errors
        }

        if c._config and not c.in_limbo and not c.config_invalid:
            status["current_config"] = model_to_dict(c._config)
            status["sync_jobs"] = {}
            for key, value in c._config.sync_jobs.items():
                if value.active:
                    job_state = sync_state.get_job_state(key)
                    status["sync_jobs"][key] = model_to_dict(value)
                    status["sync_jobs"][key].update({
                        "last_sync": job_state["last_sync"].isoformat() if job_state["last_sync"] else None,
                        "next_run": job_state["next_run"].isoformat() if job_state["next_run"] else None,
                        "sync_status": standardize_status(job_state["sync_status"]),
                        "resync_status": standardize_status(job_state["resync_status"]),
                        "hash_warnings": c.hash_warnings.get(key, False)
                    })

        return json.dumps(status, default=json_serializer, ensure_ascii=False)
    except Exception as e:
        error_message = f"Error generating status report: {str(e)}"
        log_error(error_message)
        return json.dumps({"status": "error", "message": error_message})


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
        return json.dumps({"status": "error", "message": error_message})


def standardize_status(status):
    if isinstance(status, dict):
        # If it's a dict, return the most relevant status
        # Adjust this logic based on your specific requirements
        return next((v for v in status.values() if v != "NONE"), "NONE")
    return status if status is not None else "NONE"
