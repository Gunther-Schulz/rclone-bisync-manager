import os
import subprocess
from datetime import datetime
from rclone_bisync_manager.utils import is_cpulimit_installed, check_local_rclone_test, check_remote_rclone_test, ensure_local_directory
from rclone_bisync_manager.logging_utils import log_message, log_error
from rclone_bisync_manager.config import config, sync_state


def perform_sync_operations(key, force_bisync=False, force_resync=False):
    value = config._config.sync_jobs[key]
    local_path = os.path.join(config._config.local_base_path, value.local)
    remote_path = f"{value.rclone_remote}:{value.remote}"

    if not check_local_rclone_test(local_path) or not check_remote_rclone_test(remote_path):
        return

    ensure_local_directory(local_path)

    log_message(f"Performing sync operation for {key}. Force bisync: {force_bisync}, Force resync: {force_resync}, Dry run: {config._config.dry_run}")

    status = read_status(key)
    log_message(f"Current resync status for {key}: {status['resync_status']}")

    if force_resync or status["resync_status"] in ["NONE", "IN_PROGRESS"]:
        log_message(f"Initiating resync for {key}. Force resync: {force_resync}, Resync status: {status['resync_status']}")
        write_status(key, resync_status="IN_PROGRESS")
        resync_result = resync(key, remote_path, local_path)
        write_status(key, resync_status=resync_result)

        if resync_result == "COMPLETED":
            log_message(f"Resync completed for {key}, proceeding with bisync.")
            bisync_result = bisync(key, remote_path, local_path, force_bisync)
            write_status(key, sync_status=bisync_result)
        else:
            log_error(f"Resync failed for {key}. Manual intervention or force resync required.")
            return
    else:
        log_message(f"Proceeding with bisync for {key}. Force bisync: {force_bisync}")
        bisync_result = bisync(key, remote_path, local_path, force_bisync)
        write_status(key, sync_status=bisync_result)

    sync_state.update_job_state(key, 
                                sync_status=bisync_result if 'bisync_result' in locals() else status["sync_status"],
                                resync_status=resync_result if 'resync_result' in locals() else status["resync_status"],
                                last_sync=datetime.now())
    config.save_sync_state()


def bisync(key, remote_path, local_path, force_bisync):
    log_message(f"Bisync started for {local_path} at {datetime.now()}" +
                (" - Performing a dry run" if config._config.dry_run else "") +
                (f" - Force bisync {'enabled' if force_bisync else 'disabled'}"))

    # Set the initial log position
    config._last_log_position = get_log_file_position()

    rclone_args = ['rclone', 'bisync', remote_path, local_path]
    rclone_args.extend(get_rclone_args(
        config._config.bisync_options, 'bisync', key))

    if force_bisync:
        rclone_args.append('--force')

    result = run_rclone_command(rclone_args)

    # Check for hash warnings in the log file
    check_for_hash_warnings(key)

    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Bisync")
    log_message(f"Bisync status for {local_path}: {sync_result}")
    return sync_result


def resync(key, remote_path, local_path):
    value = config._config.sync_jobs[key]
    log_message(f"Resync called with force_resync: {value.force_resync}")

    log_message(f"Resync started for {local_path} at {datetime.now(
    )}" + (" - Performing a dry run" if config._config.dry_run else ""))

    rclone_args = ['rclone', 'bisync', remote_path, local_path, '--resync']
    rclone_args.extend(get_rclone_args(
        config._config.resync_options, 'resync', key))

    result = run_rclone_command(rclone_args)
    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Resync")
    log_message(f"Resync status for {local_path}: {sync_result}")

    return sync_result


def get_rclone_args(options, operation_type, job_key):
    args = []

    # Determine which options to use based on operation type
    if operation_type == 'bisync':
        default_options = config._config.bisync_options
    elif operation_type == 'resync':
        default_options = config._config.resync_options
    else:
        default_options = {}

    # Merge options in the correct order of precedence
    job_options = config._config.sync_jobs[job_key].rclone_options
    merged_options = {
        **config._config.rclone_options,  # Global options
        **default_options,                # Operation-specific options
        **job_options,                    # Job-specific options
        **options                         # Function-call specific options
    }

    # Apply CLI overrides
    merged_options['dry_run'] = config._config.dry_run
    merged_options['force'] = config._config.sync_jobs[job_key].force_operation

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

    if config._config.redirect_rclone_log_output and hasattr(config._config, 'log_file_path'):
        args.extend(['--log-file', config._config.log_file_path])

    return args


def run_rclone_command(rclone_args):

    if is_cpulimit_installed():
        cpulimit_command = ['cpulimit',
                            f'--limit={config._config.max_cpu_usage_percent}', '--']
        cpulimit_command.extend(rclone_args)
        log_message(f"Running with cpulimit: {' '.join(cpulimit_command)}")
        return subprocess.run(cpulimit_command, capture_output=True, text=True)
    else:
        log_message(f"Rclone command parameters: {' '.join(rclone_args)}")
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

    if result_code != 0 and result_code != 9:
        config.update_sync_error(local_path, sync_type, result_code, message)
    else:
        config.remove_sync_error(local_path)

    if result_code == 0 or result_code == 9:
        log_message(f"{sync_type} {message} for {local_path}.")
        return "COMPLETED"
    else:
        log_error(f"{sync_type} {message} for {local_path}.")
        return "FAILED"


def write_status(job_key, sync_status=None, resync_status=None):
    if config._config.dry_run:
        return  # Don't update status if it's a dry run
    if sync_status is not None:
        sync_state.sync_status[job_key] = sync_status
    if resync_status is not None:
        sync_state.resync_status[job_key] = resync_status
    sync_state.last_sync_times[job_key] = datetime.now()
    config.save_sync_state()


def read_status(job_key):
    sync_status = sync_state.sync_status.get(job_key, "NONE")
    resync_status = sync_state.resync_status.get(job_key, "NONE")
    last_sync_time = sync_state.last_sync_times.get(job_key)
    return {
        "sync_status": sync_status,
        "resync_status": resync_status,
        "last_sync_time": last_sync_time
    }


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
                chunk_size = 4096
                warning_detected = False
                while True:
                    chunk = log_file.read(chunk_size)
                    if not chunk:
                        break
                    if "WARNING: hash unexpectedly blank despite Fs support" in chunk:
                        warning_detected = True
                        break

                if warning_detected:
                    warning_message = f"WARNING: Detected blank hash warnings for {
                        key}. This may indicate issues with Live Photos or other special file types. You should try to resync and if that is not successful you should consider using --ignore-size for future syncs."
                    log_message(warning_message)
                    config.hash_warnings[key] = warning_message
                else:
                    config.hash_warnings[key] = None

        config._last_log_position = current_position
