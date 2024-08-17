import os
import socket
import json
import threading
from rclone_bisync_manager.config import config, sync_state


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
        data = conn.recv(1024).decode()
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
            response = generate_status_report()  # This is already JSON
        else:
            response = json.dumps({
                "status": "error",
                "message": "Invalid command"
            })
        conn.sendall(response.encode())
    except Exception as e:
        error_response = json.dumps({
            "status": "error",
            "message": f"Error: {str(e)}"
        })
        conn.sendall(error_response.encode())
    finally:
        conn.close()


def generate_status_report():
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
        "config_file_location": config.config_file,
        "log_file_location": config._config.log_file_path if config._config else None,
        "sync_jobs": {}
    }

    if config._config and not config.in_limbo and not config.config_invalid:
        for key, value in config._config.sync_jobs.items():
            if value.active:
                job_state = sync_state.get_job_state(key)
                status["sync_jobs"][key] = {
                    "last_sync": job_state["last_sync"].isoformat() if job_state["last_sync"] else None,
                    "next_run": job_state["next_run"].isoformat() if job_state["next_run"] else None,
                    "sync_status": job_state["sync_status"],
                    "resync_status": job_state["resync_status"],
                    "force_resync": value.force_resync,
                    "hash_warnings": config.hash_warnings.get(key, False)
                }

    return json.dumps(status)
