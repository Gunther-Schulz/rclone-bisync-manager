import os
import logging
from datetime import datetime
from config import console_log

log_file_path = None
logger = None


def ensure_log_file_path():
    global log_file_path, logger
    log_dir = os.path.join(os.environ.get('XDG_DATA_HOME', os.path.expanduser(
        '~/.local/share')), 'rclone-bisync-manager')
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, 'rclone-bisync-manager.log')

    logger = logging.getLogger('rclone_bisync_manager')
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    if console_log:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)


def log_message(message):
    if logger:
        logger.info(message)


def log_error(message):
    if logger:
        logger.error(message)
