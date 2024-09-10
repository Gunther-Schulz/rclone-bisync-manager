import os
import socket
import json
import threading
from pathlib import Path

from pydantic import BaseModel
from rclone_bisync_manager.config import config, sync_state, get_config_schema
from typing import Any
from datetime import datetime, date

from rclone_bisync_manager.logging_utils import log_error
from rclone_bisync_manager.logging_utils import log_message


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
        data = conn.recv(4096).decode().strip()

        if data == "RELOAD":
            from rclone_bisync_manager.daemon_functions import reload_config
            success = reload_config()
            response = json.dumps({
                "status": "success" if success else "error",
                "message": "Configuration reloaded successfully" if success else f"Error reloading configuration. Daemon is in limbo state. Error: {config.config_error_message}"
            })
        elif data == "STOP":
            config.running = False
            config.shutting_down = True
            response = json.dumps({
                "status": "success",
                "message": "Shutdown signal sent to daemon"
            })
        elif data == "STATUS":
            response = generate_status_report()
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


def generate_status_report():
    try:
        status = {
            "pid": os.getpid(),
            "running": config.running,
            "shutting_down": config.shutting_down,
            "in_limbo": config.in_limbo,
            "config_invalid": config.config_invalid,
            "config_error_message": getattr(config, 'config_error_message', None),
            "currently_syncing": config.currently_syncing,
            "queued_paths": list(config.queued_paths),
            "config_changed_on_disk": config.config_changed_on_disk,
            "config_file_location": str(config.config_file),
            "log_file_location": str(config._config.log_file_path) if config._config else None,
            "sync_errors": config.sync_errors,
            "config_schema": get_config_schema()
        }

        if config._config and not config.in_limbo and not config.config_invalid:
            status["current_config"] = model_to_dict(config._config)
            status["sync_jobs"] = {}
            for key, value in config._config.sync_jobs.items():
                if value.active:
                    job_state = sync_state.get_job_state(key)
                    status["sync_jobs"][key] = model_to_dict(value)
                    status["sync_jobs"][key].update({
                        "last_sync": job_state["last_sync"].isoformat() if job_state["last_sync"] else None,
                        "next_run": job_state["next_run"].isoformat() if job_state["next_run"] else None,
                        "sync_status": job_state["sync_status"],
                        "resync_status": job_state["resync_status"],
                        "hash_warnings": config.hash_warnings.get(key, False)
                    })

        try:
            return json.dumps(status, default=json_serializer, ensure_ascii=False)
        except TypeError as e:
            log_error(f"JSON serialization error: {str(e)}")
            return json.dumps({"status": "error", "message": f"Error serializing status report: {str(e)}"})
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
