import os
import subprocess
import shutil
import hashlib

import psutil
from rclone_bisync_manager.logging_utils import log_message, log_error
from rclone_bisync_manager.config import config
import fcntl
import errno


def is_cpulimit_installed():
    return shutil.which('cpulimit') is not None


def check_local_rclone_test(local_path):
    result = subprocess.run(['rclone', 'lsf', local_path],
                            capture_output=True, text=True)
    if result.returncode != 0:
        log_error(f"Local rclone test failed for {local_path}")
        return False
    if config.rclone_test_file_name not in result.stdout:
        log_message(f"{config.rclone_test_file_name} file not found in {
                    local_path}. To add it run 'rclone touch \"{local_path}/{config.rclone_test_file_name}\"'")
        return False
    return True


def check_remote_rclone_test(remote_path):
    result = subprocess.run(['rclone', 'lsf', remote_path],
                            capture_output=True, text=True)
    if result.returncode != 0:
        log_error(f"Remote rclone test failed for {remote_path}")
        return False
    if config.rclone_test_file_name not in result.stdout:
        log_message(f"{config.rclone_test_file_name} file not found in {
                    remote_path}. To add it run 'rclone touch \"{remote_path}/{config.rclone_test_file_name}\"'")
        return False
    return True


def ensure_local_directory(local_path):
    if not os.path.exists(local_path):
        os.makedirs(local_path, exist_ok=True)
        log_message(f"Created local directory: {local_path}")


def check_tools():
    required_tools = ['rclone']
    for tool in required_tools:
        if shutil.which(tool) is None:
            log_error(
                f"{tool} is not installed or not in PATH. Please install it and try again.")
            exit(1)


def ensure_rclone_dir():
    rclone_dir = os.path.join(os.environ['HOME'], '.cache', 'rclone', 'bisync')
    if not os.access(rclone_dir, os.W_OK):
        os.makedirs(rclone_dir, exist_ok=True)
        os.chmod(rclone_dir, 0o777)


def handle_filter_changes():
    if not config._config or not config._config.exclusion_rules_file:
        return
    stored_md5_file = os.path.join(config.cache_dir, '.filter_md5')
    os.makedirs(config.cache_dir, exist_ok=True)
    if os.path.exists(config._config.exclusion_rules_file):
        current_md5 = calculate_md5(config._config.exclusion_rules_file)
        if os.path.exists(stored_md5_file):
            with open(stored_md5_file, 'r') as f:
                stored_md5 = f.read().strip()
        else:
            stored_md5 = ""
        if current_md5 != stored_md5:
            with open(stored_md5_file, 'w') as f:
                f.write(current_md5)
            log_message("Filter file has changed. A resync is required.")
            for job_key in config._config.sync_jobs:
                config._config.sync_jobs[job_key].force_resync = True
    else:
        log_message(f"Exclusion rules file not found: {config._config.exclusion_rules_file}")


def calculate_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def ensure_log_file_path():
    global log_file_path, error_log_file_path
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    os.makedirs(os.path.dirname(error_log_file_path), exist_ok=True)


def check_and_create_lock_file():
    lock_file_path = '/tmp/rclone_bisync_manager.lock'

    if os.path.exists(lock_file_path):
        try:
            with open(lock_file_path, 'r') as lock_file:
                pid = int(lock_file.read().strip())
            if psutil.pid_exists(pid):
                process = psutil.Process(pid)
                if any('rclone-bisync-manager' in arg for arg in process.cmdline()):
                    return None, f"Daemon is already running (PID: {pid})"
            # If we reach here, the PID doesn't exist or isn't our process
            os.remove(lock_file_path)
        except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
            os.remove(lock_file_path)

    try:
        lock_fd = os.open(lock_file_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(lock_fd, str(os.getpid()).encode())
        return lock_fd, None
    except IOError as e:
        if e.errno == errno.EEXIST:
            return None, "Unable to create lock file. Another instance might be starting."
        return None, f"Unexpected error creating lock file: {str(e)}"
