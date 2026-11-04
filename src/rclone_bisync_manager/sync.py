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

# rclone's "fatal error" exit. A bisync that aborts critically returns this -- but exit 7 alone
# does not say whether a resync is needed. With --resilient, rclone also exits 7 on a transient
# error (a dropped listing call) and says the next run may retry WITHOUT --resync. Which of the
# two it was is read from rclone's own output (resync_verdict), never assumed from the code.
RESYNC_REQUIRED_EXIT_CODES = (7,)
RESYNC_REQUIRED_MARKER = "Must run --resync to recover"
RESYNC_NOT_REQUIRED_MARKER = "retryable without --resync"

# A resync is not a neutral repair: for every file that differs it keeps one side's version and
# overwrites the other. Plain --resync means --resync-mode path1, and path1 is the remote, so a
# local edit not yet uploaded is replaced by the remote's older copy. Unless the job configures
# otherwise, the newer file wins, and the local file it replaces is moved to a backup directory
# beside the job (inside local_base_path, outside every job's own path) instead of vanishing.
RESYNC_DEFAULT_MODE = "newer"
RESYNC_BACKUP_DIRNAME = ".rclone-bisync-backups"


def resync_verdict(output):
    """What rclone said about recovering from an aborted bisync: 'required', 'retryable' or
    'unknown'. 'required' wins if both appear -- it is rclone's stronger statement."""
    text = output or ""
    if RESYNC_REQUIRED_MARKER in text:
        return "required"
    if RESYNC_NOT_REQUIRED_MARKER in text:
        return "retryable"
    return "unknown"


def notify_user(title, body):
    """Desktop notification from the daemon. Scheduled runs have no tray action behind them, so
    without this a resync or an unexplained abort is visible only to someone reading the log."""
    import shutil
    import subprocess

    log_message(f"NOTIFY: {title} -- {body}", logging.WARNING)
    if not shutil.which("notify-send"):
        log_error("notify-send not found; the notification above reached the log only.")
        return
    try:
        subprocess.run(["notify-send", "--app-name=rclone-bisync-manager", "--urgency=critical",
                        title, body], timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        log_error(f"Could not deliver desktop notification: {e}")


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
                bisync_result, _, _ = bisync(key, remote_path, local_path, context)
                write_status(key, sync_status=bisync_result, context=context)
            else:
                error_msg = f"Resync failed for {key}. It will be retried on the next run."
                log_error(error_msg)
                raise SyncError(error_msg)
        else:
            log_message(f"Proceeding with bisync for {key}. Force bisync: {context.force_bisync}")
            bisync_result, bisync_code, bisync_output = bisync(key, remote_path, local_path, context)
            write_status(key, sync_status=bisync_result, context=context)

            if bisync_result != "COMPLETED" and bisync_code in RESYNC_REQUIRED_EXIT_CODES:
                verdict = resync_verdict(bisync_output)
                if verdict == "required":
                    # rclone's listings are gone or unusable. Without this the job would run the
                    # same doomed bisync on every future tick forever, since nothing else ever
                    # moves resync_status off COMPLETED.
                    log_error(
                        f"Bisync for {key} aborted with exit {bisync_code}; rclone says "
                        f"'{RESYNC_REQUIRED_MARKER}'. Scheduling a resync for the next run."
                    )
                    resync_result = "FAILED"
                    write_status(key, resync_status=resync_result, context=context)
                elif verdict == "retryable":
                    log_error(
                        f"Bisync for {key} aborted with exit {bisync_code}; rclone says the error "
                        f"is {RESYNC_NOT_REQUIRED_MARKER}. The next run retries the bisync."
                    )
                else:
                    msg = (
                        f"Bisync for {key} aborted with exit {bisync_code} and rclone's output "
                        f"says neither '{RESYNC_REQUIRED_MARKER}' nor "
                        f"'{RESYNC_NOT_REQUIRED_MARKER}'. Not resyncing automatically: check the "
                        f"rclone log, then run `rclone-bisync-manager sync {key} --resync` if needed."
                    )
                    log_error(msg)
                    notify_user(f"Bisync {key}: aborted, needs a look", msg)

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
    run_start = context.log_state.last_log_position

    rclone_args = ['rclone', 'bisync', remote_path, local_path]
    rclone_args.extend(get_rclone_args('bisync', context))

    result = run_rclone_command(rclone_args, context)
    output = run_output(result, context, run_start)

    check_for_hash_warnings(key, context)

    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Bisync", store=context.state_store or get_sync_state_store()
    )
    log_message(f"Bisync status for {local_path}: {sync_result}")
    return sync_result, result.returncode, output


def run_output(result, context, start):
    """Everything rclone said during this run: its stderr (where it logs without --log-file) plus
    the lines it appended to its log file since `start`."""
    parts = [getattr(result, "stderr", None) or ""]
    path = getattr(context, "rclone_log_file_path", None)
    if path and os.path.exists(path) and os.path.getsize(path) > start:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(start)
            parts.append(f.read())
    return "\n".join(parts)


def resync_safety_args(key, local_path, context, stamp):
    """--resync-mode and --backup-dir2 for a resync, unless the job's options already set them.

    The backup directory is per job and per run, under local_base_path but outside the job's own
    path: rclone refuses an overlapping backup dir, and one inside the job would be synced up as
    data. A job whose path contains the base gets no backup dir rather than an aborted resync."""
    merged = {
        **context.rclone_options,
        **context.resync_options,
        **context.job.rclone_options,
        **context.job.resync_options,
    }
    args = []
    if "resync_mode" not in merged:
        args.extend(["--resync-mode", RESYNC_DEFAULT_MODE])
    if "backup_dir2" not in merged:
        backup = os.path.join(str(context.local_base_path), RESYNC_BACKUP_DIRNAME, key, stamp)
        local = os.path.abspath(local_path)
        if os.path.commonpath([os.path.abspath(backup), local]) == local:
            log_error(f"Resync of {key}: job path {local} contains {backup}; "
                      f"no backup dir for replaced local files on this run.")
        else:
            args.extend(["--backup-dir2", backup])
    return args


def list_backed_up_files(args):
    """Files rclone moved into this run's --backup-dir2, as paths relative to it."""
    if "--backup-dir2" not in args:
        return None, []
    backup = args[args.index("--backup-dir2") + 1]
    found = []
    for root, _dirs, files in os.walk(backup):
        for name in files:
            found.append(os.path.relpath(os.path.join(root, name), backup))
    return backup, sorted(found)


def resync(key, remote_path, local_path, context):
    log_message(f"Resync called with force_resync: {context.force_resync}")

    log_message(f"Resync started for {local_path} at {datetime.now()}" +
                (" - Performing a dry run" if context.dry_run else ""))

    safety = resync_safety_args(key, local_path, context, datetime.now().strftime("%Y%m%d_%H%M%S"))
    rclone_args = ['rclone', 'bisync', remote_path, local_path, '--resync']
    rclone_args.extend(get_rclone_args('resync', context))
    rclone_args.extend(safety)
    log_message(f"Resync safety options for {key}: {' '.join(safety) or '(configured by the job)'}")

    result = run_rclone_command(rclone_args, context)
    sync_result = handle_rclone_exit_code(
        result.returncode, local_path, "Resync", store=context.state_store or get_sync_state_store()
    )
    log_message(f"Resync status for {local_path}: {sync_result}")

    if not context.dry_run:
        backup, replaced = list_backed_up_files(safety)
        for rel in replaced:
            log_message(f"Resync of {key} replaced local file {rel}; previous version in {backup}",
                        logging.WARNING)
        if replaced:
            body = (f"{len(replaced)} local file(s) replaced; previous versions kept in {backup}: "
                    + ", ".join(replaced[:5]) + (" ..." if len(replaced) > 5 else ""))
        elif backup:
            body = "No local file was replaced."
        else:
            body = "Replaced local files were not backed up (see the daemon log)."
        notify_user(f"Resync of {key}: {sync_result}", body)

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
    # rclone's documented exit codes (https://rclone.org/docs/#exit-code). 1 and 2 used to be
    # described as "non-critical, a rerun may be successful" and "critically aborted" -- neither
    # is what rclone means, so a bad option in the config reported itself as a transient error the
    # user was invited to retry, forever.
    messages = {
        0: "completed successfully",
        1: "Syntax or usage error (check the rclone options in your config).",
        2: "Error not otherwise categorised, please check the logs for more information.",
        3: "Directory not found, please check the logs for more information.",
        4: "File not found, please check the logs for more information.",
        5: "Temporary error. More retries might fix this issue.",
        6: "Less serious errors, please check the logs for more information.",
        7: "Fatal error (a retry will not help; bisync usually needs a resync to recover).",
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
