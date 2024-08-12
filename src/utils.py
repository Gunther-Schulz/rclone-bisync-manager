import os
import subprocess
import shutil
from datetime import datetime, timedelta
from config import config_file, last_config_mtime, exclusion_rules_file
from logging_utils import log_message, log_error


def is_cpulimit_installed():
    return shutil.which('cpulimit') is not None


def parse_interval(interval_str):
    units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    unit = interval_str[-1]
    if unit not in units:
        raise ValueError(f"Invalid interval unit: {unit}")
    try:
        value = int(interval_str[:-1])
    except ValueError:
        raise ValueError(f"Invalid interval value: {interval_str[:-1]}")
    return value * units[unit]


def check_local_rclone_test(local_path):
    try:
        subprocess.run(['rclone', 'lsf', local_path],
                       check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        log_error(f"Local rclone test failed for {local_path}")
        return False


def check_remote_rclone_test(remote_path):
    try:
        subprocess.run(['rclone', 'lsf', remote_path],
                       check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        log_error(f"Remote rclone test failed for {remote_path}")
        return False


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
    rclone_dir = os.path.expanduser('~/.config/rclone')
    if not os.path.exists(rclone_dir):
        os.makedirs(rclone_dir, exist_ok=True)
        log_message(f"Created rclone config directory: {rclone_dir}")


def handle_filter_changes():
    if exclusion_rules_file and os.path.exists(exclusion_rules_file):
        from config import sync_jobs
        for key, value in sync_jobs.items():
            local_path = os.path.join(value['local'])
            filter_file = os.path.join(local_path, '.filter')
            if not os.path.exists(filter_file) or os.path.getmtime(filter_file) < os.path.getmtime(exclusion_rules_file):
                shutil.copy2(exclusion_rules_file, filter_file)
                log_message(f"Updated filter file for {key}")


def check_config_changed():
    global last_config_mtime
    current_mtime = os.path.getmtime(config_file)
    if current_mtime > last_config_mtime:
        last_config_mtime = current_mtime
        return True
    return False
