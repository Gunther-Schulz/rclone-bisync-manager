import yaml
import os
import sys
import subprocess
import argparse
from datetime import datetime
import signal
import atexit
import logging

# TODO: Add option for which side to prefer when doing a resync
# TODO: Maybe try one of the speed-up options for bisync for gunther

# Note: Send a SIGINT twice to force exit

# Set the locale to UTF-8 to handle special characters correctly
os.environ['LC_ALL'] = 'C.UTF-8'

# Default arguments
dry_run = False
force_resync = False
console_log = False
specific_folder = None

# Initialize variables
base_dir = os.path.join(os.environ['HOME'], '.config', 'rclone_bisync')
pid_file = os.path.join(base_dir, 'rclone_bisync.pid')
config_file = os.path.join(base_dir, 'config.yaml')
resync_status_file_name = ".resync_status"
bisync_status_file_name = ".bisync_status"
sync_log_file_name = "sync.log"
sync_error_log_file_name = "sync_error.log"
rclone_test_file_name = "RCLONE_TEST"
opt_max_lock = "15m"
opt_compare = "size,modtime,checksum"

exclude_patterns = [
    '*.tmp',
    '*.log',
    r'._.*',
    '.DS_Store',
    '.Spotlight-V100/**',
    '.Trashes/**',
    '.fseventsd/**',
    '.AppleDouble/**',
    '.VolumeIcon.icns'
]

# Global counter for CTRL-C presses
ctrl_c_presses = 0

# Global list to keep track of subprocesses
subprocesses = []


# Handle CTRL-C
def signal_handler(signal_received, frame):
    global ctrl_c_presses
    ctrl_c_presses += 1

    if ctrl_c_presses > 1:
        print('Multiple CTRL-C detected. Forcing exit.')
        os._exit(1)  # Force exit immediately

    print('SIGINT or CTRL-C detected. Exiting gracefully.')
    for proc in subprocesses:
        if proc.poll() is None:  # Subprocess is still running
            proc.send_signal(signal.SIGINT)
        proc.wait()  # Wait indefinitely until subprocess terminates
    remove_pid_file()
    sys.exit(0)


# Set the signal handler
signal.signal(signal.SIGINT, signal_handler)


# Logging
def log_message(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"{timestamp} - {message}\n"
    with open(log_file_path, 'a') as f:
        f.write(log_entry)
    if console_log:
        print(log_entry, end='')


# Logging errors
def log_error(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    error_entry = f"{timestamp} - ERROR: {message}\n"
    with open(log_file_path, 'a') as f:
        f.write(error_entry)
    with open(error_log_file_path, 'a') as f:
        f.write(f"{timestamp} - {message}\n")
    if console_log:
        print(error_entry, end='')


# Check if the script is already running
def check_pid():
    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            pid = f.read().strip()
        # Check if the process is still running
        try:
            os.kill(int(pid), 0)
            # log_error(f"Script is already running with PID {pid}.")
            sys.exit(1)
        except OSError:
            # log_message(f"Removing stale PID file {pid_file}.")
            os.remove(pid_file)

    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    # Register the cleanup function to remove the PID file at exit
    atexit.register(remove_pid_file)


# Remove the PID file
def remove_pid_file():
    if os.path.exists(pid_file):
        os.remove(pid_file)
        # log_message("PID file removed.")


# Load the configuration file
def load_config():
    global local_base_path, exclusion_rules_file, max_delete_percentage, sync_paths, log_directory, max_cpu_usage_percent, log_level
    if not os.path.exists(base_dir):
        os.makedirs(base_dir, exist_ok=True)
    if not os.path.exists(config_file):
        print(f"Configuration file not found. Please ensure it exists at: {
              config_file}")
        sys.exit(1)
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    local_base_path = config.get('local_base_path')
    exclusion_rules_file = config.get('exclusion_rules_file')
    max_delete_percentage = config.get('max_delete_percentage', 5)
    sync_paths = config.get('sync_paths', {})
    log_directory = config.get('log_directory')
    max_cpu_usage_percent = config.get('max_cpu_usage_percent', 100)
    log_level = config.get('log_level', 'INFO')


# Parse command line arguments
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', nargs='?', default=None,
                        help='Specify a folder to sync (optional).')
    parser.add_argument('-d', '--dry-run', action='store_true',
                        help='Perform a dry run without making any changes.')
    parser.add_argument('--resync', action='store_true',
                        help='Force a resynchronization, ignoring previous sync status.')
    parser.add_argument('--force-bisync', action='store_true',
                        help='Force the operation without confirmation, only applicable if a specific folder is specified.')
    parser.add_argument('--console-log', action='store_true',
                        help='Print log messages to the console in addition to the log files.')
    args, unknown = parser.parse_known_args()
    global dry_run, force_resync, console_log, specific_folder, force_operation
    dry_run = args.dry_run
    force_resync = args.resync
    console_log = args.console_log
    specific_folder = args.folder
    force_operation = args.force_bisync

    if specific_folder:
        if specific_folder not in sync_paths:
            print(f"ERROR: The specified folder '{
                  specific_folder}' is not configured in the sync directories. Please check the configuration file at {config_file}.")
            sys.exit(1)

    if force_operation and specific_folder:
        local_path = os.path.join(
            local_base_path, sync_paths[specific_folder]['local'])
        remote_path = f"{sync_paths[specific_folder]['rclone_remote']}:{
            sync_paths[specific_folder]['remote']}"
        confirmation = input(f"WARNING: You are about to force a bisync on '{
                             local_path}' and '{remote_path}'. Are you sure? (yes/no): ")
        if confirmation.lower() != 'yes':
            print("Operation aborted by the user.")
            sys.exit(0)
    elif force_operation and not specific_folder:
        print(
            "ERROR: --force-bisync can only be used when a specific sync_dir is specified.")
        sys.exit(1)


# Check if the required tools are installed
def check_tools():
    required_tools = ["rclone", "mkdir", "grep", "awk", "find", "md5sum"]
    for tool in required_tools:
        if subprocess.call(['which', tool], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            print(f"{tool} could not be found, please install it.",
                  file=sys.stderr)
            sys.exit(1)


# Ensure the rclone directory exists.
def ensure_rclone_dir():
    rclone_dir = os.path.join(os.environ['HOME'], '.cache', 'rclone', 'bisync')
    if not os.access(rclone_dir, os.W_OK):
        os.makedirs(rclone_dir, exist_ok=True)
        os.chmod(rclone_dir, 0o777)


# Ensure log directory exists
def ensure_log_directory():
    os.makedirs(log_directory, exist_ok=True)
    global log_file_path, error_log_file_path
    log_file_path = os.path.join(log_directory, sync_log_file_name)
    error_log_file_path = os.path.join(log_directory, sync_error_log_file_name)


# Calculate the MD5 of a file
def calculate_md5(file_path):
    result = subprocess.run(['md5sum', file_path],
                            capture_output=True, text=True)
    return result.stdout.split()[0]


# Handle filter changes
def handle_filter_changes():
    stored_md5_file = os.path.join(base_dir, '.filter_md5')
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
            global force_resync
            force_resync = True


# Handle the exit code of rclone
def handle_rclone_exit_code(result_code, local_path, sync_type):
    messages = {
        0: "completed successfully",
        1: "Non-critical error. A rerun may be successful.",
        2: "Critically aborted, please check the logs for more information.",
        3: "Directory not found, please check the logs for more information.",
        4: "File not found, please check the logs for more information.",
        5: "Temporary error. More retries might fix this issue.",
        6: "Less serious errors, please check the logs for more information.",
        7: "Fatal error, please check the logs for more information.",
        8: "Transfer limit exceeded, please check the logs for more information.",
        9: "successful but no files were transferred.",
        10: "Duration limit exceeded, please check the logs for more information."
    }
    message = messages.get(
        result_code, f"failed with an unknown error code {result_code}, please check the logs for more information.")
    if result_code == 0 or result_code == 9:
        log_message(f"{sync_type} {message} for {local_path}.")
        return "COMPLETED"
    else:
        log_error(f"{sync_type} {message} for {local_path}.")
        return "FAILED"


# Perform a bisync
def bisync(remote_path, local_path):
    log_message(f"Bisync started for {local_path} at {
                datetime.now()}" + (" - Performing a dry run" if dry_run else ""))

    rclone_args = [
        'rclone', 'bisync', remote_path, local_path,
        '--retries', '3',
        '--low-level-retries', '10',
        '--exclude', resync_status_file_name,
        '--exclude', bisync_status_file_name,
        '--log-file', os.path.join(log_directory, sync_log_file_name),
        '--log-level', log_level if not dry_run else 'INFO',
        '--conflict-resolve', 'newer',
        '--conflict-loser', 'num',
        '--conflict-suffix', 'rc-conflict',
        '--max-delete', str(max_delete_percentage),
        '--recover',
        '--resilient',
        '--max-lock', opt_max_lock,
        '--compare', opt_compare,
        '--create-empty-src-dirs',
        '--track-renames',
        '--check-access',
    ]

    for pattern in exclude_patterns:
        rclone_args.extend(['--exclude', pattern])
    if os.path.exists(exclusion_rules_file):
        rclone_args.extend(['--exclude-from', exclusion_rules_file])
    if dry_run:
        rclone_args.append('--dry-run')
    if force_operation:
        rclone_args.append('--force')

    # Wrap the rclone command with cpulimit
    # Limiting CPU usage to the specified limit
    cpulimit_command = ['cpulimit', '--limit=' +
                        str(max_cpu_usage_percent), '--']
    cpulimit_command.extend(rclone_args)

    result = subprocess.run(cpulimit_command, capture_output=True, text=True)
    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Bisync")
    log_message(f"Bisync status for {local_path}: {sync_result}")
    write_sync_status(local_path, sync_result)


def resync(remote_path, local_path):
    if force_resync:
        log_message("Force resync requested.")
    else:
        sync_status = read_resync_status(local_path)
        if sync_status == "COMPLETED":
            log_message("No resync necessary. Skipping.")
            return sync_status
        elif sync_status == "IN_PROGRESS":
            log_message("Resuming interrupted resync.")
        elif sync_status == "FAILED":
            log_error(
                f"Previous resync failed. Manual intervention required. Status: {sync_status}. Check the logs at {log_file_path} to fix the issue and remove the file {os.path.join(local_path, resync_status_file_name)} to start a new resync. Exiting...")
            sys.exit(1)

    log_message(f"Resync started for {local_path} at {
                datetime.now()}" + (" - Performing a dry run" if dry_run else ""))

    write_resync_status(local_path, "IN_PROGRESS")

    rclone_args = [
        'rclone', 'bisync', remote_path, local_path,
        '--resync',
        '--log-file', os.path.join(log_directory, sync_log_file_name),
        '--log-level', log_level if not dry_run else 'INFO',
        '--retries', '3',
        '--low-level-retries', '10',
        '--error-on-no-transfer',
        '--exclude', resync_status_file_name,
        '--exclude', bisync_status_file_name,
        '--max-delete', str(max_delete_percentage),
        '--recover',
        '--resilient',
        '--max-lock', opt_max_lock,
        '--compare', opt_compare,
        '--create-empty-src-dirs',
        '--check-access'
    ]

    for pattern in exclude_patterns:
        rclone_args.extend(['--exclude', pattern])
    if os.path.exists(exclusion_rules_file):
        rclone_args.extend(['--exclude-from', exclusion_rules_file])
    if dry_run:
        rclone_args.append('--dry-run')

    # Limiting CPU usage to the specified limit
    cpulimit_command = ['cpulimit', '--limit=' +
                        str(max_cpu_usage_percent), '--']
    cpulimit_command.extend(rclone_args)

    result = subprocess.run(cpulimit_command, capture_output=True, text=True)
    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Resync")
    log_message(f"Resync status for {local_path}: {sync_result}")
    write_resync_status(local_path, sync_result)

    return sync_result


# Write the sync status
def write_sync_status(local_path, sync_status):
    sync_status_file = os.path.join(local_path, bisync_status_file_name)
    if not dry_run:
        with open(sync_status_file, 'w') as f:
            f.write(sync_status)


# Write the resync status
def write_resync_status(local_path, sync_status):
    sync_status_file = os.path.join(local_path, resync_status_file_name)
    if not dry_run:
        with open(sync_status_file, 'w') as f:
            f.write(sync_status)


# Read the resync status
def read_resync_status(local_path):
    sync_status_file = os.path.join(local_path, resync_status_file_name)
    if os.path.exists(sync_status_file):
        with open(sync_status_file, 'r') as f:
            return f.read().strip()
    return "NONE"


# Ensure the local directory exists. If not, create it.
def ensure_local_directory(local_path):
    if not os.path.exists(local_path):
        os.makedirs(local_path)
        log_message(f"Local directory {local_path} created.")


def check_local_rclone_test(local_path):
    # use rclone lsf to check if the file exists
    result = subprocess.run(['rclone', 'lsf', local_path],
                            capture_output=True, text=True)
    if not rclone_test_file_name in result.stdout:
        log_message(f"{rclone_test_file_name} file not found in {
                    local_path}. To add it run 'rclone touch \"{local_path}/{rclone_test_file_name}\"'")
        return False
    return True


def check_remote_rclone_test(remote_path):
    # use rclone lsf to check if the file exists
    result = subprocess.run(['rclone', 'lsf', remote_path],
                            capture_output=True, text=True)
    if not rclone_test_file_name in result.stdout:
        log_message(f"{rclone_test_file_name} file not found in {
                    remote_path}. To add it run 'rclone touch \"{remote_path}/{rclone_test_file_name}\"'")
        return False
    return True


# Perform the sync operations
def perform_sync_operations():
    if specific_folder and specific_folder not in sync_paths:
        log_error(f"Folder '{
                  specific_folder}' is not configured in sync directories. Make sure it is in the list of sync_dirs in the configuration file at {config_file}.")
        return

    for key, value in sync_paths.items():
        if specific_folder and specific_folder != key:
            continue  # Skip folders not specified by the user
        local_path = os.path.join(local_base_path, value['local'])
        remote_path = f"{value['rclone_remote']}:{value['remote']}"

        if not check_local_rclone_test(local_path) or not check_remote_rclone_test(remote_path):
            return

        ensure_local_directory(local_path)
        if resync(remote_path, local_path) == "COMPLETED":
            bisync(remote_path, local_path)


def main():
    check_pid()
    load_config()
    parse_args()
    check_tools()
    ensure_rclone_dir()
    ensure_log_directory()
    handle_filter_changes()
    perform_sync_operations()


if __name__ == "__main__":
    main()
