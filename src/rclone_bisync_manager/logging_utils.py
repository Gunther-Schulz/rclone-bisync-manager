import logging
import os
from datetime import datetime
import sys

config = None  # We'll set this later


class BasicLogger:
    def _should_print(self, level):
        min_level = getattr(config, "min_console_level", 0) if config else 0
        return not min_level or level >= min_level

    def error(self, message):
        if not self._should_print(logging.ERROR):
            return
        print(f"ERROR: {message}", file=sys.stderr)

    def info(self, message):
        if not self._should_print(logging.INFO):
            return
        print(f"INFO: {message}")

    def log(self, level, message):
        if not self._should_print(level):
            return
        if level >= logging.ERROR:
            self.error(message)
        else:
            self.info(message)


logger = BasicLogger()


def ensure_log_file_path():
    if config and getattr(config, "log_file_path", None):
        os.makedirs(os.path.dirname(config.log_file_path), exist_ok=True)


def setup_loggers(console_log=False):
    global logger, config
    if config:
        config.console_log = console_log
        if getattr(config, "log_file_path", None):
            ensure_log_file_path()
            logger = FileLogger(config.log_file_path)


class FileLogger:
    def __init__(self, file_path):
        self.file_path = file_path

    def log(self, level, message):
        if isinstance(level, int):
            level = logging.getLevelName(level) or "INFO"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} - {level} - {message}\n"
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(log_entry)

    def info(self, message):
        self.log("INFO", message)

    def error(self, message):
        self.log("ERROR", message)


def log_message(message, level=logging.INFO):
    logger.log(level, message)
    if config and getattr(config, "console_log", False) and getattr(config, "log_file_path", None):
        min_level = getattr(config, "min_console_level", 0)
        if level >= min_level:
            if level >= logging.ERROR:
                print(f"ERROR: {message}", file=sys.stderr)
            else:
                print(message)


def log_error(message):
    logger.error(message)
    if config and getattr(config, "console_log", False) and getattr(config, "log_file_path", None):
        min_level = getattr(config, "min_console_level", 0)
        if logging.ERROR >= min_level:
            print(f"ERROR: {message}", file=sys.stderr)


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
