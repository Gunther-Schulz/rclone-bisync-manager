import os
from datetime import datetime

config = None  # We'll set this later
daemon_console_log = False


def ensure_log_file_path():
    os.makedirs(os.path.dirname(config.log_file_path), exist_ok=True)


def setup_loggers(console_log=False):
    global logger, error_logger
    ensure_log_file_path()
    logger = FileLogger(config.log_file_path)
    error_logger = FileLogger(config.error_log_file_path)
    config.console_log = console_log


class FileLogger:
    def __init__(self, file_path):
        self.file_path = file_path

    def log(self, level, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} - {level} - {message}\n"
        with open(self.file_path, 'a') as f:
            f.write(log_entry)

    def info(self, message):
        self.log("INFO", message)

    def error(self, message):
        self.log("ERROR", message)


def log_message(message):
    logger.info(message)
    if config.console_log or (config.daemon_mode and config.daemon_console_log):
        print(message)


def log_error(message):
    error_logger.error(message)
    if config.console_log or (config.daemon_mode and config.daemon_console_log):
        print(f"ERROR: {message}")


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


def log_status_server_error(e):
    log_error(f"Error in status server: {str(e)}")


def set_config(cfg):
    global config
    config = cfg
