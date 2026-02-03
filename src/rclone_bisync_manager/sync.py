import os
import subprocess
from datetime import datetime
from rclone_bisync_manager.utils import is_cpulimit_installed, check_local_rclone_test, check_remote_rclone_test, ensure_local_directory
from rclone_bisync_manager.logging_utils import log_message, log_error
from rclone_bisync_manager.sync_state_store import get_sync_state_store


def perform_sync_operations(key, force_bisync=False, force_resync=False, context=None):
    """Run resync/bisync for one job. Requires context (from build_sync_context). Caller should set config_obj._last_log_position = context.log_state.last_log_position after return."""
    if context is None:
        raise ValueError("perform_sync_operations requires context.")
    value = context.job
    local_path = os.path.join(context.local_base_path, value.local)
    remote_path = f"{value.rclone_remote}:{value.remote}"

    if not check_local_rclone_test(local_path) or not check_remote_rclone_test(remote_path):
        return  # Skip sync; caller still does _last_log_position = ctx.log_state.last_log_position

    ensure_local_directory(local_path)

    log_message(f"Performing sync operation for {key}. Force bisync: {force_bisync}, Force resync: {force_resync}, Dry run: {context.dry_run}")

    status = read_status(key, context=context)
    resync_status = status.get("resync_status", "NONE")
    log_message(f"Current resync status for {key}: {resync_status}")

    resync_result = status.get("resync_status", "NONE")
    bisync_result = status.get("sync_status", "NONE")

    if force_resync or resync_status in ["NONE", "IN_PROGRESS"]:
        log_message(f"Initiating resync for {key}. Force resync: {force_resync}, Resync status: {resync_status}")
        write_status(key, resync_status="IN_PROGRESS", context=context)
        resync_result = resync(key, remote_path, local_path, context)
        write_status(key, resync_status=resync_result, context=context)

        if resync_result == "COMPLETED":
            log_message(f"Resync completed for {key}, proceeding with bisync.")
            bisync_result = bisync(key, remote_path, local_path, force_bisync, context)
            write_status(key, sync_status=bisync_result, context=context)
        else:
            log_error(f"Resync failed for {key}. Manual intervention or force resync required.")
            return
    else:
        log_message(f"Proceeding with bisync for {key}. Force bisync: {force_bisync}")
        bisync_result = bisync(key, remote_path, local_path, force_bisync, context)
        write_status(key, sync_status=bisync_result, context=context)

    store = context.state_store or get_sync_state_store()
    store.sync_state.update_job_state(key,
                                       sync_status=bisync_result,
                                       resync_status=resync_result,
                                       last_sync=datetime.now())
    store.save()


def bisync(key, remote_path, local_path, force_bisync, context):
    log_message(f"Bisync started for {local_path} at {datetime.now()}" +
                (" - Performing a dry run" if context.dry_run else "") +
                (f" - Force bisync {'enabled' if force_bisync else 'disabled'}"))

    context.log_state.last_log_position = get_log_file_position(context)

    rclone_args = ['rclone', 'bisync', remote_path, local_path]
    rclone_args.extend(get_rclone_args(
        context.bisync_options, 'bisync', context.job_key, context.job, context))

    if force_bisync:
        rclone_args.append('--force')

    result = run_rclone_command(rclone_args, context)

    check_for_hash_warnings(key, context)

    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Bisync", store=context.state_store or get_sync_state_store()
    )
    log_message(f"Bisync status for {local_path}: {sync_result}")
    return sync_result


def resync(key, remote_path, local_path, context):
    value = context.job
    log_message(f"Resync called with force_resync: {value.force_resync}")

    log_message(f"Resync started for {local_path} at {datetime.now()}" +
                (" - Performing a dry run" if context.dry_run else ""))

    rclone_args = ['rclone', 'bisync', remote_path, local_path, '--resync']
    rclone_args.extend(get_rclone_args(
        context.resync_options, 'resync', context.job_key, context.job, context))

    result = run_rclone_command(rclone_args, context)
    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Resync", store=context.state_store or get_sync_state_store()
    )
    log_message(f"Resync status for {local_path}: {sync_result}")

    return sync_result


def get_rclone_args(options, operation_type, job_key, job, context):
    args = []

    if operation_type == 'bisync':
        default_options = context.bisync_options
    elif operation_type == 'resync':
        default_options = context.resync_options
    else:
        default_options = {}

    job_options = job.rclone_options
    merged_options = {
        **context.rclone_options,
        **default_options,
        **job_options,
        **options
    }

    merged_options['dry_run'] = context.dry_run
    merged_options['force'] = job.force_operation

    for opt_key, opt_value in merged_options.items():
        option_key = f"--{str(opt_key).replace('_', '-')}"
        if opt_value is None:
            args.append(option_key)
        elif isinstance(opt_value, bool):
            if opt_value:
                args.append(option_key)
        elif isinstance(opt_value, list):
            for item in opt_value:
                args.extend([option_key, str(item)])
        else:
            args.extend([option_key, str(opt_value)])

    if context.exclusion_rules_file and os.path.exists(context.exclusion_rules_file):
        args.extend(['--exclude-from', context.exclusion_rules_file])

    if context.redirect_rclone_log_output and context.log_file_path:
        args.extend(['--log-file', context.log_file_path])

    return args


def run_rclone_command(rclone_args, context):
    if is_cpulimit_installed():
        cpulimit_command = ['cpulimit',
                            f'--limit={context.max_cpu_usage_percent}', '--']
        cpulimit_command.extend(rclone_args)
        log_message(f"Running with cpulimit: {' '.join(cpulimit_command)}")
        return subprocess.run(cpulimit_command, capture_output=True, text=True)
    else:
        log_message(f"Rclone command parameters: {' '.join(rclone_args)}")
        return subprocess.run(rclone_args, capture_output=True, text=True)


def handle_rclone_exit_code(result_code, local_path, sync_type, store=None):
    """Return COMPLETED or FAILED; record/clear sync error in store. Uses get_sync_state_store() when store is None."""
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
        result_code,
        f"failed with an unknown error code {result_code}, please check the logs for more information.",
    )

    if store is None:
        store = get_sync_state_store()
    if result_code != 0 and result_code != 9:
        store.update_sync_error(local_path, sync_type, result_code, message)
    else:
        store.remove_sync_error(local_path)

    if result_code == 0 or result_code == 9:
        log_message(f"{sync_type} {message} for {local_path}.")
        return "COMPLETED"
    else:
        log_error(f"{sync_type} {message} for {local_path}.")
        return "FAILED"


def write_status(job_key, sync_status=None, resync_status=None, context=None):
    dry_run = context.dry_run if context is not None else False
    if dry_run:
        return
    store = (getattr(context, "state_store", None) if context is not None else None) or get_sync_state_store()
    if sync_status is not None:
        store.sync_state.sync_status[job_key] = sync_status
    if resync_status is not None:
        store.sync_state.resync_status[job_key] = resync_status
    store.sync_state.last_sync_times[job_key] = datetime.now()
    store.save()


def read_status(job_key, context=None):
    store = (getattr(context, "state_store", None) if context is not None else None) or get_sync_state_store()
    sync_status = store.sync_state.sync_status.get(job_key, "NONE")
    resync_status = store.sync_state.resync_status.get(job_key, "NONE")
    last_sync_time = store.sync_state.last_sync_times.get(job_key)
    return {
        "sync_status": sync_status,
        "resync_status": resync_status,
        "last_sync_time": last_sync_time
    }


def get_log_file_position(context):
    """Return current log file size for position tracking. With log rotation, position may reset when file rotates."""
    log_file_path = context.log_file_path
    if os.path.exists(log_file_path):
        return os.path.getsize(log_file_path)
    return 0


def check_for_hash_warnings(key, context):
    """Scan new log lines for hash warnings. Best-effort when log rotation is enabled (position may not match after rotate)."""
    log_file_path = context.log_file_path
    if os.path.exists(log_file_path):
        current_position = os.path.getsize(log_file_path)
        if current_position > context.log_state.last_log_position:
            with open(log_file_path, 'r', encoding='utf-8', errors='replace') as log_file:
                log_file.seek(context.log_state.last_log_position)
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
                    warning_message = (
                        f"WARNING: Detected blank hash warnings for {key}. "
                        "This may indicate issues with Live Photos or other special file types. "
                        "You should try to resync and if that is not successful you should consider "
                        "using --ignore-size for future syncs."
                    )
                    log_message(warning_message)
                    context.log_state.hash_warnings[key] = warning_message
                else:
                    context.log_state.hash_warnings[key] = None

        context.log_state.last_log_position = current_position
