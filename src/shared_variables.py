from threading import Lock
import os
from queue import Queue
from datetime import datetime


# Global variables for command line options
dry_run = False
force_resync = False
console_log = False
specific_sync_jobs = None
force_operation = False

# Global variables for daemon mode
daemon_mode = False
running = True
shutting_down = False
shutdown_complete = False
currently_syncing = None
current_sync_start_time = None
sync_queue = Queue()
queued_paths = set()
sync_lock = Lock()

# Global variables for sync operations
sync_jobs = {}
last_sync_times = {}
script_start_time = datetime.now()
last_config_mtime = 0

# File paths
config_file = os.path.join(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser(
    '~/.config')), 'rclone-bisync-manager', 'config.yaml')
cache_dir = os.path.join(os.environ.get(
    'XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'rclone-bisync-manager')
rclone_test_file_name = "RCLONE_TEST"

# Logging paths
default_log_dir = os.path.join(os.environ.get('XDG_STATE_HOME', os.path.expanduser(
    '~/.local/state')), 'rclone-bisync-manager', 'logs')
log_file_path = os.path.join(default_log_dir, 'rclone-bisync-manager.log')
error_log_file_path = os.path.join(
    default_log_dir, 'rclone-bisync-manager-error.log')


def signal_handler(signum, frame):
    global running, shutting_down
    running = False
    shutting_down = True
    from logging_utils import log_message
    log_message('SIGINT or SIGTERM received. Initiating graceful shutdown.')
