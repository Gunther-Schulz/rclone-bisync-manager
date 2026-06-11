"""Centralized subprocess execution module for consistent command execution.

This module provides a unified interface for subprocess operations,
standardizing error handling, logging, and execution patterns across
the codebase.
"""

import logging
import os
import shlex
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple, Union

from rclone_bisync_manager.logging_utils import log_error, log_message


_logger = logging.getLogger(__name__)


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
        result = subprocess.run(
            cpulimit_command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        
        if result.returncode != 0:
            error_msg = f"cpulimit command failed: {' '.join(cpulimit_command)}"
            log_error(error_msg)
            raise SubprocessError(error_msg)
        
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
    
    # Use cpulimit if specified and available
    if cpulimit_percent is not None and cpulimit_percent > 0:
        if cpulimit_percent > 100:
            error_msg = f"CPU limit percentage must be between 0 and 100, got {cpulimit_percent}"
            log_error(error_msg)
            raise SubprocessError(error_msg)
        if check_command_exists("cpulimit"):
            return run_with_cpulimit(rclone_args, cpulimit_percent, timeout)
        # cpulimit not installed: degrade gracefully and run without CPU limiting
        # rather than aborting the sync. Install cpulimit to enforce the limit.
        log_message(
            "cpulimit is not installed or not in PATH; running without CPU limiting.",
            logging.WARNING,
        )

    # No cpulimit (not requested, or not available), run directly
    return run_command(rclone_args, timeout=timeout)


def check_rclone_local(local_path: str, test_file_name: str) -> bool:
    """Check if rclone can access a local path and contains test file.
    
    Args:
        local_path: Local path to check
        test_file_name: Name of test file to look for
    
    Returns:
        True if path is accessible and contains test file, False otherwise
    """
    command = ["rclone", "lsf", local_path]
    success, stdout, stderr = check_command_output(command)
    
    if not success:
        log_error(f"Local rclone test failed for {local_path}")
        return False
    
    if test_file_name not in stdout:
        log_message(f"{test_file_name} file not found in {local_path}. "
                   f"To add it run 'rclone touch \"{local_path}/{test_file_name}\"'")
        return False
    
    return True


def check_rclone_remote(remote_path: str, test_file_name: str) -> bool:
    """Check if rclone can access a remote path and contains test file.
    
    Args:
        remote_path: Remote path to check (format: "remote:path")
        test_file_name: Name of test file to look for
    
    Returns:
        True if path is accessible and contains test file, False otherwise
    """
    command = ["rclone", "lsf", remote_path]
    success, stdout, stderr = check_command_output(command)
    
    if not success:
        log_error(f"Remote rclone test failed for {remote_path}")
        return False
    
    if test_file_name not in stdout:
        log_message(f"{test_file_name} file not found in {remote_path}. "
                   f"To add it run 'rclone touch \"{remote_path}/{test_file_name}\"'")
        return False
    
    return True


def check_local_rclone_test(local_path: str) -> bool:
    """Check if rclone can access a local path and contains the configured test file."""
    from rclone_bisync_manager.config import get_config
    cfg = get_config()
    return check_rclone_local(local_path, cfg.rclone_test_file_name)


def check_remote_rclone_test(remote_path: str) -> bool:
    """Check if rclone can access a remote path and contains the configured test file."""
    from rclone_bisync_manager.config import get_config
    cfg = get_config()
    return check_rclone_remote(remote_path, cfg.rclone_test_file_name)


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
