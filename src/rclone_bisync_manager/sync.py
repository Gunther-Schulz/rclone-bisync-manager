import logging
import os
import traceback
from datetime import datetime
from rclone_bisync_manager.subprocess_executor import (
    check_access_marker,
    execute_rclone_command,
    verify_required_tools,
)
from rclone_bisync_manager.logging_utils import log_message, log_error
from rclone_bisync_manager.utils import ensure_local_directory
from rclone_bisync_manager.sync_state_store import get_sync_state_store


# Resync states that mean "this job has no usable bisync baseline yet".
#   NONE        - never resynced.
#   IN_PROGRESS - a resync started and never recorded a result (daemon was killed).
#   FAILED      - a resync ran and failed, e.g. rclone got SIGTERM on shutdown.
# FAILED used to be missing here, which stranded the job: it would skip the resync branch
# forever and run a bisync that could never succeed without a baseline.
RESYNC_PENDING_STATES = ("NONE", "IN_PROGRESS", "FAILED")

# rclone's "fatal error" exit. A bisync that aborts critically ("Bisync aborted. Must run
# --resync to recover") returns this; it cannot be repaired by retrying the bisync.
RESYNC_REQUIRED_EXIT_CODES = (7,)


def resolve_access_check(context):
    """Resolve whether this job wants rclone's --check-access, and under which filename.

    The RCLONE_TEST marker is only required when the user asks for --check-access.
    rclone defaults that off and so do we: requiring the marker unconditionally makes
    every first-time sync fail until the user hand-creates a file nothing told them
    about. Deletions stay guarded by bisync's --max-delete (50% by default).

    A YAML `null` value means "pass the bare flag", so absent is the only "off"
    besides an explicit `false`.
    """
    from rclone_bisync_manager.config import get_config

    merged = {
        **context.rclone_options,
        **context.bisync_options,
        **context.resync_options,
        **context.job.rclone_options,
        **context.job.bisync_options,
        **context.job.resync_options,
    }
    enabled = "check_access" in merged and merged["check_access"] is not False
    marker_file = merged.get("check_filename") or get_config().rclone_test_file_name
    return enabled, marker_file


def perform_sync_operations(key, context=None):
    """Run resync/bisync for one job. Requires context (from build_sync_context); force flags come from context.force_bisync/context.force_resync. Caller should set config_obj._last_log_position = context.log_state.last_log_position after return."""
    from rclone_bisync_manager.exceptions import SyncError, ValidationError

    if context is None:
        raise ValidationError("perform_sync_operations requires context.")
    value = context.job
    local_path = os.path.join(context.local_base_path, value.local)
    remote_path = f"{value.rclone_remote}:{value.remote}"

    check_enabled, marker_file = resolve_access_check(context)
    if check_enabled:
        # Check before creating anything. If local_path is a mount point that failed to
        # mount, creating the directory first would paper over the very condition
        # --check-access exists to catch.
        problems = [
            reason
            for reason in (
                check_access_marker(local_path, marker_file),
                check_access_marker(remote_path, marker_file),
            )
            if reason is not None
        ]
        if problems:
            for reason in problems:
                log_error(reason)
            raise SyncError(f"Access check failed for {key}. " + " ".join(problems))

    ensure_local_directory(local_path)

    log_message(f"Performing sync operation for {key}. Force bisync: {context.force_bisync}, Force resync: {context.force_resync}, Dry run: {context.dry_run}")

    try:
        status = read_status(key, context=context)
        resync_status = status.get("resync_status", "NONE")
        log_message(f"Current resync status for {key}: {resync_status}")

        resync_result = status.get("resync_status", "NONE")
        bisync_result = status.get("sync_status", "NONE")

        if context.force_resync or resync_status in RESYNC_PENDING_STATES:
            log_message(f"Initiating resync for {key}. Force resync: {context.force_resync}, Resync status: {resync_status}")
            write_status(key, resync_status="IN_PROGRESS", context=context)
            resync_result, _ = resync(key, remote_path, local_path, context)
            write_status(key, resync_status=resync_result, context=context)

            if resync_result == "COMPLETED":
                log_message(f"Resync completed for {key}, proceeding with bisync.")
                bisync_result, _ = bisync(key, remote_path, local_path, context)
                write_status(key, sync_status=bisync_result, context=context)
            else:
                error_msg = f"Resync failed for {key}. It will be retried on the next run."
                log_error(error_msg)
                raise SyncError(error_msg)
        else:
            log_message(f"Proceeding with bisync for {key}. Force bisync: {context.force_bisync}")
            bisync_result, bisync_code = bisync(key, remote_path, local_path, context)
            write_status(key, sync_status=bisync_result, context=context)

            if bisync_result != "COMPLETED" and bisync_code in RESYNC_REQUIRED_EXIT_CODES:
                # rclone aborted with "Must run --resync to recover" (its listings are gone or
                # unusable). Without this the job would run the same doomed bisync on every
                # future tick forever, since nothing else ever moves resync_status off COMPLETED.
                log_error(
                    f"Bisync for {key} aborted with exit {bisync_code}; rclone requires a resync "
                    f"to recover. Scheduling a resync for the next run."
                )
                resync_result = "FAILED"
                write_status(key, resync_status=resync_result, context=context)

        if context.dry_run:
            log_message(f"Dry run for {key}: results are not written to the sync state.")
            return

        store = context.state_store or get_sync_state_store()
        store.sync_state.update_job_state(key,
                                           sync_status=bisync_result,
                                           resync_status=resync_result,
                                           last_sync=datetime.now())
        store.save()
    except Exception as e:
        log_error(f"Sync failed for job '{key}': {e}\n{traceback.format_exc()}")
        raise SyncError(f"Sync failed for job '{key}': {str(e)}")


def bisync(key, remote_path, local_path, context):
    log_message(f"Bisync started for {local_path} at {datetime.now()}" +
                (" - Performing a dry run" if context.dry_run else "") +
                (f" - Force bisync {'enabled' if context.force_bisync else 'disabled'}"))

    rotate_rclone_log_if_large(context)
    # Record where rclone's log ends BEFORE the run, so afterwards we scan only this run's lines.
    context.log_state.last_log_position = get_log_file_position(context)

    rclone_args = ['rclone', 'bisync', remote_path, local_path]
    rclone_args.extend(get_rclone_args('bisync', context))

    result = run_rclone_command(rclone_args, context)

    check_for_hash_warnings(key, context)

    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Bisync", store=context.state_store or get_sync_state_store()
    )
    log_message(f"Bisync status for {local_path}: {sync_result}")
    return sync_result, result.returncode


def resync(key, remote_path, local_path, context):
    log_message(f"Resync called with force_resync: {context.force_resync}")

    log_message(f"Resync started for {local_path} at {datetime.now()}" +
                (" - Performing a dry run" if context.dry_run else ""))

    rclone_args = ['rclone', 'bisync', remote_path, local_path, '--resync']
    rclone_args.extend(get_rclone_args('resync', context))

    result = run_rclone_command(rclone_args, context)
    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Resync", store=context.state_store or get_sync_state_store()
    )
    log_message(f"Resync status for {local_path}: {sync_result}")

    return sync_result, result.returncode


def get_rclone_args(operation_type, context):
    args = []
    job = context.job

    if operation_type == 'bisync':
        global_op_options = context.bisync_options
        job_op_options = job.bisync_options
    elif operation_type == 'resync':
        global_op_options = context.resync_options
        job_op_options = job.resync_options
    else:
        global_op_options, job_op_options = {}, {}

    # Most specific wins. The global op-options dict used to be spread LAST (it was passed in
    # twice), so a global option overrode the job's own -- a job trying to be stricter than the
    # global silently lost. job.bisync_options / job.resync_options were never read at all.
    merged_options = {
        **context.rclone_options,
        **global_op_options,
        **job.rclone_options,
        **job_op_options,
    }

    merged_options['dry_run'] = context.dry_run

    if context.force_bisync and operation_type == 'bisync':
        # --force does exactly one thing in bisync: bypass the --max-delete guard. Only add it
        # where it means something -- resync doesn't delete -- and never leave it implicit.
        log_message(
            f"Force requested for {context.job_key}: passing --force, which DISABLES rclone's "
            f"--max-delete safety check for this run. Deletions will not be capped.",
            logging.WARNING,
        )
        merged_options['force'] = True
    else:
        merged_options.pop('force', None)

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
        # --filters-file, not --exclude-from: bisync hashes the filters file and aborts if it
        # changed without a resync. It does not track --exclude-from at all, so a changed file
        # would silently propagate the newly-excluded files as deletions.
        args.extend(['--filters-file', context.exclusion_rules_file])

    if context.redirect_rclone_log_output and context.rclone_log_file_path:
        # rclone's own log file, not the daemon's: see rclone_log_path().
        args.extend(['--log-file', context.rclone_log_file_path])

    return args


def run_rclone_command(rclone_args, context):
    """Execute rclone command using subprocess executor module."""
    return execute_rclone_command(
        rclone_args=rclone_args,
        cpulimit_percent=context.max_cpu_usage_percent,
        max_cpu_usage_percent=context.max_cpu_usage_percent,
        timeout=None,
    )


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


def rotate_rclone_log_if_large(context, max_bytes=50 * 1024 * 1024):
    """Rotate rclone's log before a run if it has grown past max_bytes.

    rclone has no log rotation of its own, and it appends. Rotating here is safe because each sync
    starts a fresh rclone: between runs nobody holds the file open. Returns True if rotated, in
    which case the caller's saved byte offset is meaningless and must be reset.
    """
    path = context.rclone_log_file_path
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= max_bytes:
            return False
        os.replace(path, path + ".1")
        log_message(f"Rotated rclone log (>{max_bytes // (1024 * 1024)} MB) to {path}.1")
        return True
    except OSError as e:
        log_error(f"Could not rotate rclone log {path}: {e}")
        return False


def get_log_file_position(context):
    """Byte offset into rclone's log to start scanning from after the next run."""
    log_file_path = context.rclone_log_file_path
    if os.path.exists(log_file_path):
        return os.path.getsize(log_file_path)
    return 0


def check_for_hash_warnings(key, context):
    """Scan the lines rclone appended during this run for hash warnings.

    Reads rclone's own log file. It used to read the DAEMON's log, whose rotation would shrink
    the file below the saved offset -- after which this scanned nothing at all, silently.
    """
    log_file_path = context.rclone_log_file_path
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
