"""Centralized subprocess execution module for consistent command execution.

This module provides a unified interface for subprocess operations,
standardizing error handling, logging, and execution patterns across
the codebase.
"""

import logging
import os
import shlex
import shutil
import signal
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

from rclone_bisync_manager.logging_utils import log_error, log_message


_logger = logging.getLogger(__name__)

# The rclone process currently running a sync, so shutdown can actually stop it. Nothing held a
# handle before: rclone was launched with a blocking subprocess.run, so `daemon stop` could only
# wait for it to finish on its own -- hours, for a large resync.
_current_child_lock = threading.Lock()
_current_child: Optional[subprocess.Popen] = None


def _run_tracked(command: List[str], timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    """Run a command as a tracked child in its own process group.

    Its own session means terminate_current_child() can signal the whole group, which matters when
    cpulimit wraps rclone: signalling cpulimit alone would leave rclone running.
    """
    global _current_child
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    with _current_child_lock:
        _current_child = proc
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    finally:
        with _current_child_lock:
            _current_child = None
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def terminate_current_child(grace_seconds: float = 30) -> bool:
    """Terminate the running rclone, if any. Returns True if one was signalled.

    Aborting a bisync is safe to do: rclone leaves the prior listings intact, and a job left
    needing repair re-enters the resync branch on its next run (see sync.RESYNC_PENDING_STATES).
    """
    with _current_child_lock:
        proc = _current_child
    if proc is None or proc.poll() is not None:
        return False
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        return False

    log_message(f"Stopping rclone (pid {proc.pid}) so the daemon can shut down.", logging.WARNING)
    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        return False
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        log_message(f"rclone ignored SIGTERM for {grace_seconds}s; killing it.", logging.WARNING)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass
    return True


class SubprocessError(Exception):
    """Base exception for subprocess execution errors."""
    
    def __init__(self, message: str, returncode: int = None, stdout: str = None, stderr: str = None):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def run_command(
    command: List[str],
    capture_output: bool = True,
    text: bool = True,
    check: bool = False,
    env: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess command with standardized error handling.
    
    Args:
        command: List of command arguments
        capture_output: Capture stdout and stderr (default: True)
        text: Use text mode (default: True)
        check: Raise exception if returncode != 0 (default: False)
        env: Optional environment variables (overrides default)
    
    Returns:
        CompletedProcess object with stdout, stderr, and returncode
    
    Raises:
        SubprocessError: If command fails and check=True
    """
    try:
        result = subprocess.run(
            command,
            capture_output=capture_output,
            text=text,
            check=check,
            env=env,
            timeout=timeout,
        )
        return result
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {' '.join(shlex.quote(str(arg)) for arg in command)}")
        log_error(f"Return code: {e.returncode}")
        log_error(f"Stdout: {e.stdout}")
        log_error(f"Stderr: {e.stderr}")
        raise SubprocessError(
            f"Command failed: {' '.join(shlex.quote(str(arg)) for arg in command)}",
            returncode=e.returncode,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e


def check_command_exists(command: str) -> bool:
    """Check if a command exists on the system PATH.
    
    Args:
        command: Command name to check
    
    Returns:
        True if command exists, False otherwise
    """
    return shutil.which(command) is not None


def check_command_output(
    command: List[str],
    expected_content: Optional[str] = None,
    ignore_patterns: Optional[List[str]] = None,
) -> Tuple[bool, str, str]:
    """Run a command and check its output.
    
    Args:
        command: List of command arguments
        expected_content: Optional string that should be in output
        ignore_patterns: Optional list of regex patterns to ignore in output
    
    Returns:
        Tuple of (success, stdout, stderr)
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        
        success = result.returncode == 0
        
        # Check for expected content
        if expected_content and success:
            stdout_str = result.stdout
            if expected_content not in stdout_str:
                log_message(f"Expected content not found in output: {expected_content}")
                success = False
        
        # Check for ignored patterns
        if ignore_patterns and success and result.stdout:
            import re
            for pattern in ignore_patterns:
                if re.search(pattern, result.stdout, re.IGNORECASE):
                    log_message(f"Ignored pattern found in output: {pattern}")
                    success = False
        
        return success, result.stdout or "", result.stderr or ""
    
    except Exception as e:
        log_error(f"Error running command: {e}")
        return False, "", str(e)


def get_command_output(
    command: List[str],
    timeout: Optional[float] = None,
) -> str:
    """Run a command and return its stdout.
    
    Args:
        command: List of command arguments
        timeout: Optional timeout in seconds
    
    Returns:
        Command stdout as string
    
    Raises:
        SubprocessError: If command fails
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
        return result.stdout or ""
    
    except subprocess.TimeoutExpired:
        error_msg = f"Command timed out: {' '.join(shlex.quote(str(arg)) for arg in command)}"
        log_error(error_msg)
        raise SubprocessError(error_msg)
    
    except subprocess.CalledProcessError as e:
        error_msg = f"Command failed: {' '.join(shlex.quote(str(arg)) for arg in command)}"
        log_error(error_msg)
        raise SubprocessError(error_msg) from e


def run_with_cpulimit(
    command: List[str],
    cpulimit_percent: int,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """Run a command wrapped with cpulimit to limit CPU usage.
    
    Args:
        command: List of command arguments
        cpulimit_percent: CPU limit percentage (0-100)
        timeout: Optional timeout in seconds
    
    Returns:
        CompletedProcess object
    
    Raises:
        SubprocessError: If cpulimit is not installed or command fails
    """
    if not check_command_exists("cpulimit"):
        error_msg = "cpulimit is not installed or not in PATH. CPU limiting will not be enabled."
        log_error(error_msg)
        raise SubprocessError(error_msg)
    
    cpulimit_command = ["cpulimit", f"--limit={cpulimit_percent}", "--"]
    cpulimit_command.extend(command)

    try:
        result = _run_tracked(cpulimit_command, timeout=timeout)

        # Return the CompletedProcess whatever the exit code: it is rclone's, and only the
        # caller can classify it. Raising here skipped handle_rclone_exit_code entirely, so a
        # failed sync kept its previous "COMPLETED" status and never reached sync_errors --
        # and exit 9 ("nothing transferred", a SUCCESS under --error-on-no-transfer) looked
        # like a failure, leaving resync_status IN_PROGRESS and resyncing forever.
        return result
    
    except subprocess.TimeoutExpired:
        error_msg = f"Command timed out: {' '.join(shlex.quote(str(arg)) for arg in command)}"
        log_error(error_msg)
        raise SubprocessError(error_msg)
    
    except Exception as e:
        error_msg = f"Error running cpulimit: {e}"
        log_error(error_msg)
        raise SubprocessError(error_msg) from e


def execute_rclone_command(
    rclone_args: List[str],
    cpulimit_percent: Optional[int] = None,
    max_cpu_usage_percent: int = 100,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """Execute an rclone command with standardized options.
    
    Args:
        rclone_args: List of rclone arguments
        cpulimit_percent: Optional CPU limit percentage (overrides max_cpu_usage_percent)
        max_cpu_usage_percent: Maximum CPU usage percentage (default: 100)
        timeout: Optional timeout in seconds
    
    Returns:
        CompletedProcess object
    """
    if not check_command_exists("rclone"):
        error_msg = "rclone is not installed or not in PATH. Please install it and try again."
        log_error(error_msg)
        raise SubprocessError(error_msg)
    
    if cpulimit_percent is not None and not (0 <= cpulimit_percent <= 100):
        error_msg = f"CPU limit percentage must be between 0 and 100, got {cpulimit_percent}"
        log_error(error_msg)
        raise SubprocessError(error_msg)

    # 100 means "no limit", so don't pay for the wrapper -- the default of 100 used to route
    # every single run through cpulimit.
    if cpulimit_percent is not None and 0 < cpulimit_percent < 100:
        if check_command_exists("cpulimit"):
            return run_with_cpulimit(rclone_args, cpulimit_percent, timeout)
        # cpulimit not installed: degrade gracefully and run without CPU limiting
        # rather than aborting the sync. Install cpulimit to enforce the limit.
        log_message(
            "cpulimit is not installed or not in PATH; running without CPU limiting.",
            logging.WARNING,
        )

    # No cpulimit (not requested, or not available), run directly -- still tracked, so shutdown
    # can stop it.
    return _run_tracked(rclone_args, timeout=timeout)


def check_access_marker(path: str, test_file_name: str) -> Optional[str]:
    """Check that rclone can reach path and that it holds the access-check marker.

    Only meaningful when the user enabled rclone's --check-access; we run it as a
    pre-flight so a missing marker fails fast with a fix, rather than after rclone
    has spun up a transfer.

    Args:
        path: Local path, or remote in "remote:path" form
        test_file_name: Marker filename rclone expects (--check-filename)

    Returns:
        None if the path is usable, otherwise a reason naming the fix.
    """
    success, stdout, stderr = check_command_output(["rclone", "lsf", path])

    if not success:
        detail = stderr.strip() or "rclone lsf failed"
        return f"{path} is not reachable by rclone ({detail})"

    # lsf lists one entry per line, directories with a trailing slash. Match whole
    # entries: a substring test would let RCLONE_TESTING.txt satisfy the check.
    entries = {line.rstrip("/") for line in stdout.splitlines()}
    if test_file_name not in entries:
        return (
            f"{path} has no {test_file_name} marker, which --check-access requires. "
            f"Add it with: rclone touch \"{path}/{test_file_name}\" "
            f"(or drop check_access from rclone_options to disable the check)"
        )

    return None


def verify_required_tools(tools: List[str]) -> None:
    """Verify required CLI tools are installed and on PATH.
    
    Args:
        tools: List of tool names to check
    
    Raises:
        SubprocessError: If any required tool is missing
    """
    for tool in tools:
        if not check_command_exists(tool):
            error_msg = f"{tool} is not installed or not in PATH. Please install it and try again."
            log_error(error_msg)
            raise SubprocessError(error_msg)
