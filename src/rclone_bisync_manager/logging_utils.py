import logging
import logging.handlers
import os
import sys

config = None  # We'll set this later

# Defaults for log rotation when not set in config (max size in MB, converted to bytes for RotatingFileHandler)
DEFAULT_LOG_MAX_MB = 5
DEFAULT_LOG_BACKUP_COUNT = 5

_LOGGER_NAME = "rclone_bisync_manager"
_stdlib_logger = logging.getLogger(_LOGGER_NAME)


class BasicLogger:
    """Logger that only prints to console (used when no log file is configured, e.g. tray)."""

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


# Fallback when no file logging is configured
logger = BasicLogger()


class StdLibLogger:
    """Forwards log_message/log_error to the stdlib logger (file + console via handlers)."""

    def log(self, level, message):
        _stdlib_logger.log(level, message)

    def info(self, message):
        _stdlib_logger.info(message)

    def error(self, message):
        _stdlib_logger.error(message)


def ensure_log_file_path():
    if config and getattr(config, "log_file_path", None):
        log_dir = os.path.dirname(config.log_file_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)


def _get_rotation_params():
    """Return (maxBytes, backupCount) from config or defaults. Config uses MB for max size; invalid values fall back to defaults."""
    if not config:
        return DEFAULT_LOG_MAX_MB * 1024 * 1024, DEFAULT_LOG_BACKUP_COUNT
    max_mb = getattr(config, "log_rotation_max_mb", None)
    backup_count = getattr(config, "log_rotation_backup_count", None)
    if max_mb is None or max_mb <= 0:
        max_mb = DEFAULT_LOG_MAX_MB
    if backup_count is None or backup_count < 0:
        backup_count = DEFAULT_LOG_BACKUP_COUNT
    return max_mb * 1024 * 1024, backup_count


def setup_loggers(console_log=False):
    global logger, config
    if config:
        config.console_log = console_log
    # Use stdlib logger for all output; add/remove handlers based on config
    _stdlib_logger.setLevel(logging.DEBUG)
    _stdlib_logger.handlers.clear()
    if config and getattr(config, "log_file_path", None):
        ensure_log_file_path()
        max_bytes, backup_count = _get_rotation_params()
        file_handler = logging.handlers.RotatingFileHandler(
            config.log_file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        _stdlib_logger.addHandler(file_handler)
        logger = StdLibLogger()
    else:
        logger = BasicLogger()
    # Only add console handlers when using file logging (StdLibLogger); BasicLogger prints directly.
    if config and getattr(config, "console_log", False) and getattr(config, "log_file_path", None):
        min_console = getattr(config, "min_console_level", logging.INFO)
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(min_console)
        stream_handler.addFilter(lambda r: r.levelno < logging.ERROR)  # INFO/WARNING to stdout only
        stream_handler.setFormatter(logging.Formatter("%(message)s"))
        _stdlib_logger.addHandler(stream_handler)
        err_handler = logging.StreamHandler(sys.stderr)
        err_handler.setLevel(logging.ERROR)
        err_handler.setFormatter(logging.Formatter("ERROR: %(message)s"))
        _stdlib_logger.addHandler(err_handler)


def log_message(message, level=logging.INFO):
    """Log to file and/or console. BasicLogger prints directly; StdLibLogger uses handlers."""
    logger.log(level, message)


def log_error(message):
    """Log error to file and/or console."""
    logger.error(message)


def log_config_file_location(config_file):
    log_message(f"Config file location: {config_file}")


def set_config(cfg):
    global config
    config = cfg
