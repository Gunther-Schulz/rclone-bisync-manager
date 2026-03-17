"""Centralized socket communication module for consistent error handling.

This module provides a unified interface for socket operations,
standardizing error handling, retry logic, and communication patterns
across the codebase.
"""

import json
import os
import socket
import time
from typing import Any, Dict, Optional, Tuple, Union

from rclone_bisync_manager.logging_utils import log_error, log_message
from rclone_bisync_manager import status_protocol as sp


class SocketError(Exception):
    """Base exception for socket communication errors."""
    
    def __init__(self, message: str, error_type: str = None):
        super().__init__(message)
        self.error_type = error_type


class SocketTimeoutError(SocketError):
    """Exception for socket timeout errors."""
    pass


class SocketCommunicationError(SocketError):
    """Exception for general socket communication errors."""
    pass


def _recv_all(sock, timeout: float = 5) -> str:
    """Read until connection closes (for variable-length JSON).
    
    Args:
        sock: Socket object
        timeout: Timeout in seconds
    
    Returns:
        Received data as string
    
    Raises:
        SocketTimeoutError: If timeout occurs
        SocketCommunicationError: If communication fails
    """
    sock.settimeout(timeout)
    chunks = []
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode('utf-8', errors='replace')
    except socket.timeout:
        raise SocketTimeoutError(f"Socket timeout after {timeout} seconds")
    except (socket.error, OSError) as e:
        raise SocketCommunicationError(f"Socket communication error: {e}")


def _request_status_once(
    socket_path: str,
    command: str,
    timeout: float = 5
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Single attempt at STATUS command.
    
    Args:
        socket_path: Path to status socket
        command: Command to send ("STATUS", "RELOAD", "STOP", "GET_CONFIG")
        timeout: Timeout in seconds
    
    Returns:
        Tuple of (result_dict, retryable_error) or (None, None) on success
    """
    client = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(socket_path)
        client.sendall(command.encode('utf-8'))
        response = _recv_all(client)
        return (json.loads(response) if response else None, None)
    except (socket.error, json.JSONDecodeError) as e:
        return (None, True)
    finally:
        if client is not None:
            try:
                client.close()
            except OSError:
                pass


def request_status(
    timeout: float = 5,
    retries: int = 0,
    retry_delay: float = 0.5
) -> Optional[Dict[str, Any]]:
    """Request STATUS from daemon. Returns parsed dict or None on error.
    
    When retries > 0, retries on socket/JSON errors (e.g. daemon busy with another request).
    
    Args:
        timeout: Timeout per request in seconds
        retries: Number of retry attempts
        retry_delay: Delay between retries in seconds
    
    Returns:
        Parsed status dict or None on error
    """
    socket_path = sp.get_status_socket_path()
    if not socket_path or not os.path.exists(socket_path):
        return None
    
    for attempt in range(1 + max(0, retries)):
        if attempt > 0:
            time.sleep(retry_delay)
        result, _ = _request_status_once(socket_path, "STATUS", timeout)
        if result is not None:
            return result
    return None


def request_reload(
    timeout: float = 5,
) -> Optional[Dict[str, Any]]:
    """Send RELOAD to daemon. Returns dict with 'status' and 'message', or None if daemon not running.
    
    Args:
        timeout: Timeout in seconds
    
    Returns:
        Response dict or None if daemon not running
    """
    socket_path = sp.get_status_socket_path()
    if not socket_path or not os.path.exists(socket_path):
        return None
    
    client = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(socket_path)
        client.sendall(b"RELOAD")
        response = client.recv(4096).decode('utf-8', errors='replace')
        return json.loads(response) if response else {"status": "error", "message": "No response"}
    except (socket.error, json.JSONDecodeError) as e:
        log_error(f"Error sending RELOAD command: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        if client is not None:
            try:
                client.close()
            except OSError:
                pass


def _request_stop_once(
    socket_path: str,
    timeout: float = 5
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Single attempt at STOP command.
    
    Args:
        socket_path: Path to status socket
        timeout: Timeout in seconds
    
    Returns:
        Tuple of (result_dict, retryable_error)
    """
    client = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(socket_path)
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


def request_stop(
    timeout: float = 5,
    retries: int = 0,
    retry_delay: float = 0.5
) -> Optional[Dict[str, Any]]:
    """Send STOP to daemon. Returns dict with 'status' and 'message', or None if daemon not running.
    
    When retries > 0, retries on socket/JSON errors (e.g. daemon busy with another request).
    
    Args:
        timeout: Timeout in seconds
        retries: Number of retry attempts
        retry_delay: Delay between retries in seconds
    
    Returns:
        Response dict or None if daemon not running
    """
    socket_path = sp.get_status_socket_path()
    if not socket_path or not os.path.exists(socket_path):
        return None
    
    last_result = None
    for attempt in range(1 + max(0, retries)):
        if attempt > 0:
            time.sleep(retry_delay)
        result, retryable = _request_stop_once(socket_path, timeout)
        last_result = result
        if result and result.get("status") == "success":
            return result
        if not retryable:
            return result
    return last_result


def request_config_schema(
    timeout: float = 5
) -> Dict[str, Any]:
    """Request GET_CONFIG from daemon. Returns dict with 'config_schema' or empty dict on error.
    
    Args:
        timeout: Timeout in seconds
    
    Returns:
        Response dict with config_schema or empty dict
    """
    socket_path = sp.get_status_socket_path()
    if not socket_path or not os.path.exists(socket_path):
        return {}
    
    client = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(socket_path)
        client.sendall(b"GET_CONFIG")
        response = _recv_all(client)
        data = json.loads(response) if response else {}
        return data.get("config_schema", {})
    except (socket.error, json.JSONDecodeError):
        log_error(f"Error sending GET_CONFIG command")
        return {}
    finally:
        if client is not None:
            try:
                client.close()
            except OSError:
                pass


def request_add_sync(
    job_key: str,
    force_bisync: bool = False,
    resync: bool = False,
    timeout: float = 5
) -> str:
    """Add one job to daemon sync queue. Returns 'OK' or error string.
    
    Args:
        job_key: Job key to add
        force_bisync: Whether to force bisync
        resync: Whether to force resync
        timeout: Timeout in seconds
    
    Returns:
        'OK' or error string
    """
    socket_path = sp.get_add_sync_socket_path()
    if not socket_path or not os.path.exists(socket_path):
        return "Daemon not running"
    
    client = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(socket_path)
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
