import os
import logging
from datetime import datetime

log_file_path = None
error_log_file_path = None
logger = None
error_logger = None


def ensure_log_file_path():
    global log_file_path, error_log_file_path
    default_log_dir = os.path.join(os.environ.get('XDG_STATE_HOME', os.path.expanduser(
        '~/.local/state')), 'rclone-bisync-manager', 'logs')
    os.makedirs(default_log_dir, exist_ok=True)
    log_file_path = os.path.join(default_log_dir, 'rclone-bisync-manager.log')
    error_log_file_path = os.path.join(
        default_log_dir, 'rclone-bisync-manager-error.log')


def setup_loggers(console_log=False):
    global logger, error_logger
    ensure_log_file_path()

    logger = logging.getLogger('rclone_bisync_manager')
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    error_logger = logging.getLogger('rclone_bisync_manager_error')
    error_logger.setLevel(logging.ERROR)

    error_file_handler = logging.FileHandler(error_log_file_path)
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(formatter)

    error_logger.addHandler(error_file_handler)

    if console_log:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        error_logger.addHandler(console_handler)


def log_message(message):
    if logger:
        logger.info(message)
    print(message)  # Always print to console for non-daemon mode


def log_error(message):
    if error_logger:
        error_logger.error(message)
    if logger:
        logger.error(message)
    print(f"ERROR: {message}")  # Always print errors to console


def log_initial_warning():
    log_message("Warning: This script does not prevent multiple instances from running. Please ensure you don't start it multiple times unintentionally.")


def log_home_directory():
    home_dir = os.environ.get('HOME')
    if home_dir:
        log_message(f"Home directory: {home_dir}")
    else:
        log_error("Unable to determine home directory")


def log_config_file_location(config_file):
    log_message(f"Config file location: {config_file}")


def log_sync_start(key):
    log_message(f"Starting sync for {key}")


def log_sync_end(key, status):
    log_message(f"Sync for {key} {status}")


def log_daemon_start():
    log_message("Daemon started")


def log_daemon_stop():
    log_message("Daemon stop request received. Shutting down.")


def log_daemon_shutdown_complete():
    log_message("Daemon shutdown complete.")
