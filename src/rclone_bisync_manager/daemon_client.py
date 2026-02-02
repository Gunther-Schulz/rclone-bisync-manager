"""Client for daemon status socket and add-sync socket. Single place for request/response protocol."""

import json
import os
import socket

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
    return b"".join(chunks).decode()


def request_status(timeout=5):
    """Request STATUS from daemon. Returns parsed dict or None on error."""
    path = get_status_socket_path()
    if not path or not os.path.exists(path):
        return None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(path)
        client.sendall(b"STATUS")
        response = _recv_all(client)
        client.close()
        return json.loads(response) if response else None
    except (socket.error, json.JSONDecodeError):
        return None


def request_reload(timeout=5):
    """Send RELOAD to daemon. Returns dict with 'status' and 'message', or None if daemon not running."""
    path = get_status_socket_path()
    if not path or not os.path.exists(path):
        return None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(path)
        client.sendall(b"RELOAD")
        response = client.recv(4096).decode()
        client.close()
        return json.loads(response) if response else {"status": "error", "message": "No response"}
    except (socket.error, json.JSONDecodeError) as e:
        return {"status": "error", "message": str(e)}


def request_stop(timeout=5):
    """Send STOP to daemon. Returns dict with 'status' and 'message'."""
    path = get_status_socket_path()
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(path)
        client.sendall(b"STOP")
        response = client.recv(4096).decode()
        client.close()
        return json.loads(response) if response else {"status": "error", "message": "No response"}
    except (socket.error, json.JSONDecodeError) as e:
        return {"status": "error", "message": str(e)}


def request_config_schema(timeout=5):
    """Request GET_CONFIG from daemon. Returns dict with 'config_schema' or empty dict on error."""
    path = get_status_socket_path()
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(path)
        client.sendall(b"GET_CONFIG")
        response = _recv_all(client)
        client.close()
        data = json.loads(response) if response else {}
        return data.get("config_schema", {})
    except (socket.error, json.JSONDecodeError):
        return {}


def request_add_sync(job_key, force_bisync=False, resync=False, timeout=5):
    """Add one job to daemon sync queue. Returns 'OK' or error string."""
    path = get_add_sync_socket_path()
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
        client.close()
        if response and response.strip() == "OK":
            return "OK"
        return response.strip() if response else "No response"
    except socket.error as e:
        return str(e)
