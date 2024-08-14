import os
import subprocess
from datetime import datetime
from config import config
from utils import is_cpulimit_installed, check_local_rclone_test, check_remote_rclone_test, ensure_local_directory
from logging_utils import log_message, log_error
import json
import fcntl


def perform_sync_operations(key):
    value = config._config.sync_jobs[key]
    local_path = os.path.join(config._config.local_base_path, value.local)
    remote_path = f"{value.rclone_remote}:{value.remote}"
    status_file = config.get_status_file_path(key)

    if not os.path.exists(status_file):
        log_message(f"No status file found for {key}. Forcing resync.")
        config.force_resync = True

    if not check_local_rclone_test(local_path) or not check_remote_rclone_test(remote_path):
        return

    ensure_local_directory(local_path)

    log_message(f"Performing sync operation for {key}. Force resync: {
                config.force_resync}, Dry run: {config._config.dry_run}")

    if config.force_resync:
        log_message("Force resync requested.")
        resync_result = resync(key, remote_path, local_path)
        if resync_result == "COMPLETED":
            bisync_result = bisync(key, remote_path, local_path)
            write_status(key, sync_status=bisync_result,
                         resync_status=resync_result)
    else:
        bisync_result = bisync(key, remote_path, local_path)
        write_status(key, sync_status=bisync_result)

    config.last_sync_times[key] = datetime.now()


def bisync(key, remote_path, local_path):
    log_message(f"Bisync started for {local_path} at {datetime.now(
    )}" + (" - Performing a dry run" if config._config.dry_run else ""))

    # Set the initial log position
    config._last_log_position = get_log_file_position()

    rclone_args = ['rclone', 'bisync', remote_path, local_path]
    rclone_args.extend(get_rclone_args(
        config._config.bisync_options, 'bisync'))

    result = run_rclone_command(rclone_args)

    # Check for hash warnings in the log file
    check_for_hash_warnings(key)

    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Bisync")
    log_message(f"Bisync status for {local_path}: {sync_result}")
    write_status(key, sync_status=sync_result)


def resync(key, remote_path, local_path):
    log_message(f"Resync called with force_resync: {config.force_resync}")
    if config.force_resync:
        log_message("Force resync requested.")
    else:
        _, resync_status = read_status(key)
        if resync_status == "COMPLETED":
            log_message("No resync necessary. Skipping.")
            return resync_status
        elif resync_status == "IN_PROGRESS":
            log_message("Resuming interrupted resync.")
        elif resync_status == "FAILED":
            log_error(f"Previous resync failed. Manual intervention required. Status: {resync_status}. Check the logs to fix the issue and remove the file {
                      os.path.join(local_path, '.resync_status')} to start a new resync. Exiting...")
            return resync_status

    log_message(f"Resync started for {local_path} at {datetime.now(
    )}" + (" - Performing a dry run" if config._config.dry_run else ""))

    write_status(key, resync_status="IN_PROGRESS")

    rclone_args = ['rclone', 'bisync', remote_path, local_path, '--resync']
    rclone_args.extend(get_rclone_args(
        config._config.resync_options, 'resync'))

    result = run_rclone_command(rclone_args)
    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Resync")
    log_message(f"Resync status for {local_path}: {sync_result}")
    write_status(key, resync_status=sync_result)

    return sync_result


def get_rclone_args(options, operation_type):
    args = []

    # Determine which options to use based on operation type
    if operation_type == 'bisync':
        default_options = config._config.bisync_options
    elif operation_type == 'resync':
        default_options = config._config.resync_options
    else:
        default_options = {}

    # Merge default options with rclone_options
    merged_options = {**config._config.rclone_options,
                      **default_options, **options}

    for key, value in merged_options.items():
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

    if hasattr(config._config, 'exclusion_rules_file') and os.path.exists(config._config.exclusion_rules_file):
        args.extend(['--exclude-from', config._config.exclusion_rules_file])

    # Always add --dry-run if path_dry_run is True
    if config._config.dry_run:
        args.append('--dry-run')
    if config.force_operation:
        args.append('--force')
    if config._config.redirect_rclone_log_output and hasattr(config._config, 'log_file_path'):
        args.extend(['--log-file', config._config.log_file_path])

    if merged_options.get('ignore_size', False):
        args.append('--ignore-size')

    return args


def run_rclone_command(rclone_args):
    if is_cpulimit_installed():
        cpulimit_command = ['cpulimit',
                            f'--limit={config._config.max_cpu_usage_percent}', '--']
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

    if not hasattr(config, 'sync_errors'):
        config.sync_errors = {}
    if result_code != 0 and result_code != 9:
        config.sync_errors[local_path] = {
            "sync_type": sync_type,
            "error_code": result_code,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
    else:
        if hasattr(config, 'sync_errors'):
            config.sync_errors[local_path] = None

    if result_code == 0 or result_code == 9:
        log_message(f"{sync_type} {message} for {local_path}.")
        return "COMPLETED"
    else:
        log_error(f"{sync_type} {message} for {local_path}.")
        return "FAILED"


def write_status(job_key, sync_status=None, resync_status=None):
    if config._config.dry_run:
        return  # Don't write status if it's a dry run
    status_file = config.status_file_path[job_key]
    os.makedirs(os.path.dirname(status_file), exist_ok=True)
    with open(status_file, 'a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            status = json.load(f)
        except json.JSONDecodeError:
            status = {}
        if sync_status is not None:
            status["sync_status"] = sync_status
        if resync_status is not None:
            status["resync_status"] = resync_status
        f.seek(0)
        f.truncate()
        json.dump(status, f)
        fcntl.flock(f, fcntl.LOCK_UN)


def read_status(job_key):
    status_file = config.status_file_path[job_key]
    if os.path.exists(status_file):
        with open(status_file, 'r') as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                status = json.load(f)
                return status.get("sync_status", "NONE"), status.get("resync_status", "NONE")
            except json.JSONDecodeError:
                return "NONE", "NONE"
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    return "NONE", "NONE"


def get_log_file_position():
    log_file_path = config._config.log_file_path
    if os.path.exists(log_file_path):
        return os.path.getsize(log_file_path)
    return 0


def check_for_hash_warnings(key):
    log_file_path = config._config.log_file_path
    if os.path.exists(log_file_path):
        current_position = os.path.getsize(log_file_path)
        if current_position > config._last_log_position:
            with open(log_file_path, 'r') as log_file:
                log_file.seek(config._last_log_position)
                new_content = log_file.read()
                if "WARNING: hash unexpectedly blank despite Fs support" in new_content:
                    warning_message = f"WARNING: Detected blank hash warnings for {
                        key}. This may indicate issues with Live Photos or other special file types. You should try to resync and if that is not successful you should consider using --ignore-size for future syncs."
                    log_message(warning_message)
                    config.hash_warnings[key] = warning_message
                else:
                    config.hash_warnings[key] = None

        config._last_log_position = current_position
