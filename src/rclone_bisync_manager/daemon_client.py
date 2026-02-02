"""Client for daemon status socket and add-sync socket. Single place for request/response protocol."""

import json
import os
import socket
import time

from rclone_bisync_manager.runtime_paths import (
    get_status_socket_path,
    get_add_sync_socket_path,
)


def _recv_all(sock, timeout=5):
    """Read until connection closes (for variable-length JSON)."""
    sock.settimeout(timeout)
    chunks = []
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks).decode('utf-8', errors='replace')


def _request_status_once(path, timeout=5):
    """Single attempt at STATUS. Returns (result, None) on success or (None, True) on error (retryable)."""
    client = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(path)
        client.sendall(b"STATUS")
        response = _recv_all(client)
        return (json.loads(response) if response else None, None)
    except (socket.error, json.JSONDecodeError):
        return (None, True)
    finally:
        if client is not None:
            try:
                client.close()
            except OSError:
                pass


def request_status(timeout=5, retries=0, retry_delay=0.5):
    """Request STATUS from daemon. Returns parsed dict or None on error.
    When retries > 0, retries on socket/JSON errors (e.g. daemon busy with another request)."""
    path = get_status_socket_path()
    if not path or not os.path.exists(path):
        return None
    last_err_retryable = False
    for attempt in range(1 + max(0, retries)):
        if attempt > 0:
            time.sleep(retry_delay)
        result, retryable = _request_status_once(path, timeout)
        if result is not None:
            return result
        last_err_retryable = retryable
    return None


def request_reload(timeout=5):
    """Send RELOAD to daemon. Returns dict with 'status' and 'message', or None if daemon not running."""
    path = get_status_socket_path()
    if not path or not os.path.exists(path):
        return None
    client = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(path)
        client.sendall(b"RELOAD")
        response = client.recv(4096).decode('utf-8', errors='replace')
        return json.loads(response) if response else {"status": "error", "message": "No response"}
    except (socket.error, json.JSONDecodeError) as e:
        return {"status": "error", "message": str(e)}
    finally:
        if client is not None:
            try:
                client.close()
            except OSError:
                pass


def _request_stop_once(path, timeout=5):
    """Single attempt at STOP. Returns (result_dict, None) on success or (error_dict, True) on retryable error."""
    client = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(path)
        client.sendall(b"STOP")
        response = client.recv(4096).decode('utf-8', errors='replace')
        out = json.loads(response) if response else {"status": "error", "message": "No response"}
        return (out, None)
    except (socket.error, json.JSONDecodeError) as e:
        return ({"status": "error", "message": str(e)}, True)
    finally:
        if client is not None:
            try:
                client.close()
            except OSError:
                pass


def request_stop(timeout=5, retries=0, retry_delay=0.5):
    """Send STOP to daemon. Returns dict with 'status' and 'message', or None if daemon not running.
    When retries > 0, retries on socket/JSON errors (e.g. daemon busy with another request)."""
    path = get_status_socket_path()
    if not path or not os.path.exists(path):
        return None
    last_result = None
    for attempt in range(1 + max(0, retries)):
        if attempt > 0:
            time.sleep(retry_delay)
        result, retryable = _request_stop_once(path, timeout)
        last_result = result
        if result and result.get("status") == "success":
            return result
        if not retryable:
            return result
    return last_result


def request_config_schema(timeout=5):
    """Request GET_CONFIG from daemon. Returns dict with 'config_schema' or empty dict on error."""
    path = get_status_socket_path()
    if not path or not os.path.exists(path):
        return {}
    client = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(path)
        client.sendall(b"GET_CONFIG")
        response = _recv_all(client)
        data = json.loads(response) if response else {}
        return data.get("config_schema", {})
    except (socket.error, json.JSONDecodeError):
        return {}
    finally:
        if client is not None:
            try:
                client.close()
            except OSError:
                pass


def request_add_sync(job_key, force_bisync=False, resync=False, timeout=5):
    """Add one job to daemon sync queue. Returns 'OK' or error string."""
    path = get_add_sync_socket_path()
    if not path or not os.path.exists(path):
        return "Daemon not running"
    client = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(path)
        payload = json.dumps({
            "job_key": job_key,
            "force_bisync": force_bisync,
            "resync": resync,
        })
        client.sendall(payload.encode())
        response = _recv_all(client)
        if response and response.strip() == "OK":
            return "OK"
        return response.strip() if response else "No response"
    except socket.error as e:
        return str(e)
    finally:
        if client is not None:
            try:
                client.close()
            except OSError:
                pass
