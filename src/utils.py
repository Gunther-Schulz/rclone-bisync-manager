import os
import subprocess
import shutil
import hashlib
from datetime import datetime, timedelta
from logging_utils import log_message, log_error
from interval_utils import parse_interval
from config import config_file, cache_dir, rclone_test_file_name, exclusion_rules_file, last_config_mtime


def is_cpulimit_installed():
    return shutil.which('cpulimit') is not None


def check_local_rclone_test(local_path):
    result = subprocess.run(['rclone', 'lsf', local_path],
                            capture_output=True, text=True)
    if result.returncode != 0:
        log_error(f"Local rclone test failed for {local_path}")
        return False
    if rclone_test_file_name not in result.stdout:
        log_message(f"{rclone_test_file_name} file not found in {
                    local_path}. To add it run 'rclone touch \"{local_path}/{rclone_test_file_name}\"'")
        return False
    return True


def check_remote_rclone_test(remote_path):
    result = subprocess.run(['rclone', 'lsf', remote_path],
                            capture_output=True, text=True)
    if result.returncode != 0:
        log_error(f"Remote rclone test failed for {remote_path}")
        return False
    if rclone_test_file_name not in result.stdout:
        log_message(f"{rclone_test_file_name} file not found in {
                    remote_path}. To add it run 'rclone touch \"{remote_path}/{rclone_test_file_name}\"'")
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
    log_message("All required tools are available.")


def ensure_rclone_dir():
    rclone_dir = os.path.join(os.environ['HOME'], '.cache', 'rclone', 'bisync')
    if not os.access(rclone_dir, os.W_OK):
        os.makedirs(rclone_dir, exist_ok=True)
        os.chmod(rclone_dir, 0o777)
    log_message(f"Ensured rclone directory: {rclone_dir}")


def handle_filter_changes():
    global force_resync
    if not exclusion_rules_file:
        return
    stored_md5_file = os.path.join(cache_dir, '.filter_md5')
    os.makedirs(cache_dir, exist_ok=True)  # Ensure cache directory exists
    if os.path.exists(exclusion_rules_file):
        current_md5 = calculate_md5(exclusion_rules_file)
        if os.path.exists(stored_md5_file):
            with open(stored_md5_file, 'r') as f:
                stored_md5 = f.read().strip()
        else:
            stored_md5 = ""
        if current_md5 != stored_md5:
            with open(stored_md5_file, 'w') as f:
                f.write(current_md5)
            log_message("Filter file has changed. A resync is required.")
            force_resync = True
    else:
        log_message(f"Exclusion rules file not found: {exclusion_rules_file}")


def check_config_changed():
    global last_config_mtime
    current_mtime = os.path.getmtime(config_file)
    if current_mtime > last_config_mtime:
        last_config_mtime = current_mtime
        return True
    return False


def calculate_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()
