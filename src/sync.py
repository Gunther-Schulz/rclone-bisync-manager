import os
import subprocess
from datetime import datetime, timedelta
from config import sync_jobs, local_base_path, dry_run, force_resync, force_operation, rclone_options, bisync_options, resync_options, last_sync_times
from utils import is_cpulimit_installed, parse_interval, check_local_rclone_test, check_remote_rclone_test, ensure_local_directory
from logging_utils import log_message, log_error
from scheduler import scheduler

current_sync_start_time = None


def perform_sync_operations(key):
    global current_sync_start_time
    current_sync_start_time = datetime.now()

    value = sync_jobs[key]

    local_path = os.path.join(local_base_path, value['local'])
    remote_path = f"{value['rclone_remote']}:{value['remote']}"

    if not check_local_rclone_test(local_path) or not check_remote_rclone_test(remote_path):
        current_sync_start_time = None
        return

    ensure_local_directory(local_path)

    path_dry_run = dry_run or value.get('dry_run', False)

    if resync(remote_path, local_path, path_dry_run) == "COMPLETED":
        bisync(remote_path, local_path, path_dry_run)

    # Update last sync time and schedule next run
    last_sync_times[key] = datetime.now()
    interval = parse_interval(value['sync_interval'])
    next_run = last_sync_times[key] + timedelta(seconds=interval)
    scheduler.schedule_task(key, next_run)

    current_sync_start_time = None


def bisync(remote_path, local_path, path_dry_run):
    log_message(f"Bisync started for {local_path} at {
                datetime.now()}" + (" - Performing a dry run" if path_dry_run else ""))

    rclone_args = ['rclone', 'bisync', remote_path, local_path]
    rclone_args.extend(get_rclone_args(bisync_options, path_dry_run))

    result = run_rclone_command(rclone_args)
    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Bisync")
    log_message(f"Bisync status for {local_path}: {sync_result}")
    write_sync_status(local_path, sync_result)


def resync(remote_path, local_path, path_dry_run):
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
            log_error(f"Previous resync failed. Manual intervention required. Status: {sync_status}. Check the logs to fix the issue and remove the file {
                      os.path.join(local_path, '.resync_status')} to start a new resync. Exiting...")
            return sync_status

    log_message(f"Resync started for {local_path} at {
                datetime.now()}" + (" - Performing a dry run" if path_dry_run else ""))

    write_resync_status(local_path, "IN_PROGRESS")

    rclone_args = ['rclone', 'bisync', remote_path, local_path, '--resync']
    rclone_args.extend(get_rclone_args(resync_options, path_dry_run))

    result = run_rclone_command(rclone_args)
    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Resync")
    log_message(f"Resync status for {local_path}: {sync_result}")
    write_resync_status(local_path, sync_result)

    return sync_result


def get_rclone_args(options, path_dry_run):
    args = []
    for key, value in options.items():
        option_key = f"--{key.replace('_', '-')}"
        if value is None:
            args.append(option_key)
        elif isinstance(value, bool):
            if value:
                args.append(option_key)
        elif isinstance(value, list):
            for item in value:
                args.extend([option_key, str(item)])
        else:
            args.extend([option_key, str(value)])

    if path_dry_run:
        args.append('--dry-run')
    if force_operation:
        args.append('--force')

    return args


def run_rclone_command(rclone_args):
    if is_cpulimit_installed():
        cpulimit_command = [
            'cpulimit', f'--limit={rclone_options.get("max_cpu_usage_percent", 100)}', '--']
        cpulimit_command.extend(rclone_args)
        return subprocess.run(cpulimit_command, capture_output=True, text=True)
    else:
        return subprocess.run(rclone_args, capture_output=True, text=True)


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
    message = messages.get(result_code, f"failed with an unknown error code {
                           result_code}, please check the logs for more information.")
    if result_code == 0 or result_code == 9:
        log_message(f"{sync_type} {message} for {local_path}.")
        return "COMPLETED"
    else:
        log_error(f"{sync_type} {message} for {local_path}.")
        return "FAILED"


def write_sync_status(local_path, sync_status):
    sync_status_file = os.path.join(local_path, '.bisync_status')
    if not dry_run:
        with open(sync_status_file, 'w') as f:
            f.write(sync_status)


def write_resync_status(local_path, sync_status):
    sync_status_file = os.path.join(local_path, '.resync_status')
    if not dry_run:
        with open(sync_status_file, 'w') as f:
            f.write(sync_status)


def read_resync_status(local_path):
    sync_status_file = os.path.join(local_path, '.resync_status')
    if os.path.exists(sync_status_file):
        with open(sync_status_file, 'r') as f:
            return f.read().strip()
    return "NONE"
