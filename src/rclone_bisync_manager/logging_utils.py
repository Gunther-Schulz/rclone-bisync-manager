import logging
import logging.handlers
import os
import sys

# Mutable ref so set_config/setup_loggers can assign without global keyword
_config_ref = [None]
logger_ref = [None]

# Defaults for log rotation when not set in config (max size in MB, converted to bytes for RotatingFileHandler)
DEFAULT_LOG_MAX_MB = 5
DEFAULT_LOG_BACKUP_COUNT = 5

_LOGGER_NAME = "rclone_bisync_manager"
_stdlib_logger = logging.getLogger(_LOGGER_NAME)


class BasicLogger:
    """Logger that only prints to console (used when no log file is configured, e.g. tray)."""

    def _should_print(self, level):
        cfg = _config_ref[0]
        min_level = getattr(cfg, "min_console_level", 0) if cfg else 0
        return not min_level or level >= min_level

    def error(self, message):
        if not self._should_print(logging.ERROR):
            return
        print(f"ERROR: {message}", file=sys.stderr)

    def info(self, message):
        if not self._should_print(logging.INFO):
            return
        print(f"INFO: {message}")

    def _level_name(self, level):
        if level >= logging.ERROR:
            return "ERROR"
        if level >= logging.WARNING:
            return "WARNING"
        if level >= logging.INFO:
            return "INFO"
        return "DEBUG"

    def log(self, level, message):
        if not self._should_print(level):
            return
        if level >= logging.ERROR:
            print(f"ERROR: {message}", file=sys.stderr)
        else:
            print(f"{self._level_name(level)}: {message}")


# Fallback when no file logging is configured (ref so setup_loggers can replace without global)
logger_ref[0] = BasicLogger()


class StdLibLogger:
    """Forwards log_message/log_error to the stdlib logger (file + console via handlers)."""

    def log(self, level, message):
        _stdlib_logger.log(level, message)

    def info(self, message):
        _stdlib_logger.info(message)

    def error(self, message):
        _stdlib_logger.error(message)


def ensure_log_file_path():
    cfg = _config_ref[0]
    if cfg and getattr(cfg, "log_file_path", None):
        log_dir = os.path.dirname(cfg.log_file_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)


def _get_rotation_params():
    """Return (maxBytes, backupCount) from config or defaults. Config uses MB for max size; invalid values fall back to defaults."""
    cfg = _config_ref[0]
    if not cfg:
        return DEFAULT_LOG_MAX_MB * 1024 * 1024, DEFAULT_LOG_BACKUP_COUNT
    max_mb = getattr(cfg, "log_rotation_max_mb", None)
    backup_count = getattr(cfg, "log_rotation_backup_count", None)
    if max_mb is None or max_mb <= 0:
        max_mb = DEFAULT_LOG_MAX_MB
    if backup_count is None or backup_count < 0:
        backup_count = DEFAULT_LOG_BACKUP_COUNT
    return max_mb * 1024 * 1024, backup_count


def setup_loggers(console_log=False):
    cfg = _config_ref[0]
    if cfg:
        cfg.console_log = console_log
    # Use stdlib logger for all output; add/remove handlers based on config
    _stdlib_logger.setLevel(logging.DEBUG)
    _stdlib_logger.handlers.clear()
    if cfg and getattr(cfg, "log_file_path", None):
        ensure_log_file_path()
        max_bytes, backup_count = _get_rotation_params()
        file_handler = logging.handlers.RotatingFileHandler(
            cfg.log_file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        _stdlib_logger.addHandler(file_handler)
        logger_ref[0] = StdLibLogger()
    else:
        logger_ref[0] = BasicLogger()
    # Only add console handlers when using file logging (StdLibLogger); BasicLogger prints directly.
    if cfg and getattr(cfg, "console_log", False) and getattr(cfg, "log_file_path", None):
        min_console = getattr(cfg, "min_console_level", logging.INFO)
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
    (logger_ref[0] or BasicLogger()).log(level, message)


def log_error(message):
    """Log error to file and/or console."""
    (logger_ref[0] or BasicLogger()).error(message)


def log_config_file_location(config_file):
    log_message(f"Config file location: {config_file}")


def set_config(cfg):
    _config_ref[0] = cfg
