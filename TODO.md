# TODO

## Known issues (mitigated)

- **Tray shows "Daemon Offline" when daemon runs:** Mitigated with status timeout 8s, retries (2 × 0.3s), sticky OFFLINE only after 2 consecutive None polls.
- **Stopping daemon not reliable during RUNNING:** Mitigated with retries for `request_stop`, wait-for-gone, "Stop failed" notification; UI refresh after stop.
- **Tray does not reliably show RUNNING:** Same mitigations as above; status window does show RUNNING.

## Testing

- [ ] **Manual / e2e:** Missed runs still processed; behavior when suspending PC; per-sync job options override; exclude rule file changes trigger resync.

Automated tests are in place (42 tests in `tests/`); run with `pytest tests/ -v`.

## Beta readiness

1. [x] **Tests:** Automated test suite (pytest, see above).
2. [x] **README:** Beta disclaimer ("Beta — suitable for production use with backups; please report bugs").
3. [x] **Version/classifier:** `0.3.0b1`; PyPI classifier `Development Status :: 4 - Beta`.
4. [x] **Optional:** CHANGELOG or release notes for first beta (`CHANGELOG.md` added); document known limitations (tray/stop mitigations).

## Development

- [ ] Implement internal Python CPU limiter.
- [ ] Implement separate filter files per job.

## Improvements

- [x] Refactor to eliminate remaining `global` keyword in system_tray.py (config/scheduler/logger done: daemon uses injection; logging_utils and sync_state_store use mutable refs, no global keyword). Done: TrayState + _tray_state_ref, get_tray_state/set_tray_state; all tray code uses state from ref.

## Issues and hardening

- [ ] **Status payload size:** Very large payload (many/large jobs) can cause long receive time or high memory. Options: slim STATUS (omit/truncate `current_config` or per-job details), or document practical limit.

---

## Completed (reference)

- Status JSON truncation: fixed via `_recv_all()` in daemon_client.
- Socket leak in daemon_client: fixed (socket always closed in `finally`).
- Tray UX: status timeout 8s, retries, sticky OFFLINE, stop retries, wait-for-gone, "Stop failed" notification.
- Atomic write for sync_state.json / sync_errors.json (`.tmp` + `os.replace()`).
- Optional retry for STOP/status when daemon busy; tray uses retries.
- Log: log_file_path from YAML; RotatingFileHandler; optional log_rotation_max_mb / log_rotation_backup_count in config.
- Pre-commit hook: `githooks/pre-commit` runs pytest; install with `git config core.hooksPath githooks`.
- **Refactor (CLIPPY):** sync decoupled from global config (perform_sync_operations requires context; SyncContext.state_store; write_status/read_status/handle_rclone_exit_code use context.store or fallback). Daemon path uses injected _daemon_config and _daemon_scheduler (set in run_daemon_start before DaemonContext). Exception handling: run_sync and process_sync_queue catch sync failures and log (with traceback in daemon); skip logging when queued job no longer in config.

---

## Refactor status (done vs left)

Verified in code 2025-02-03; table updated after tray refactor, error/exit unification, and StatusResponse TypedDict.

| # | Topic | Done | Left |
|---|--------|------|------|
| 1 | Global state | DaemonRuntimeState, SyncStateStore. Daemon path: _daemon_config, _daemon_scheduler injected. logging_utils/sync_state_store use refs (no global keyword). Tray: TrayState + _tray_state_ref, get_tray_state/set_tray_state (no global keyword). | `config`/scheduler still module-level (main/commands/CLI). |
| 2 | main / orchestration | Thin main → run_command; commands.py; runtime_paths + daemon_client. Daemon phases (Bootstrap / Lock / Daemonize / Run loop). | — |
| 3 | Paths | runtime_paths.py: sockets, lock, crash log; env_dir(RCLONE_BISYNC_MANAGER_RUNTIME_DIR, XDG_RUNTIME_DIR). | — |
| 4 | Config class | LogStatePersistence as Config property (_log_state). SyncStateStore/DaemonRuntimeState are separate (not Config props). | Config still: config_file, load_and_validate_config, status_file_path, check_config_changed / last_config_mtime. |
| 5 | Coupling | status_server(handlers=, state=, config=). sync no longer imports config; uses context.state_store, context.dry_run; callers set _last_log_position. | — |
| 6 | Tray vs core | Shared daemon_client, status_protocol, runtime_paths. DaemonState + status_to_display_state. Unified logging_utils. Tray state via TrayState + ref (no global). | — |
| 7 | Logging | Core and tray: logging_utils (log_message, log_error, set_config, setup_loggers). | — |
| 8 | Error / exit | main sys.exit(result); crash log in runtime_paths (clear/write/read). commands return 0/1; run_daemon_start returns 1 on failure; daemon child sys.exit(1) documented. | — |
| 9 | Sync / scheduler | SyncContext + build_sync_context(..., state_store=); perform_sync_operations(..., context=ctx) requires context; context.state_store used; handle_rclone_exit_code(..., store=). | — |
| 10 | Python 3.14 | pyproject requires-python ">=3.12"; type annotations in status_protocol, runtime_paths. DEV.md free-threading note (PEP 703). StatusResponse TypedDict for status dict. | Module-level config/scheduler in main/commands remain. |
| 11 | "Refactor first" | Paths, daemon client, protocol, main thin, DaemonRuntimeState, SyncStateStore, LogStatePersistence, tray shared DTO + logging + state ref, crash log, sync decouple, daemon injection. | Immutable "loaded config" vs Config not done. |
