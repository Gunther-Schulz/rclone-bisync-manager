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

- [ ] Refactor to eliminate `global` keyword (if possible).

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

---

## Refactor status (done vs left)

| # | Topic | Done | Left |
|---|--------|------|------|
| 1 | Global state | DaemonRuntimeState, SyncStateStore. | `config` still global (80+ refs). scheduler/logger global. |
| 2 | main / orchestration | Thin main → run_command; commands.py; runtime_paths + daemon_client. Daemon phases (Bootstrap / Lock / Daemonize / Run loop). | — |
| 3 | Paths | runtime_paths.py: sockets, lock, crash log; env override (RCLONE_BISYNC_MANAGER_RUNTIME_DIR, XDG_RUNTIME_DIR). | — |
| 4 | Config class | SyncStateStore, DaemonRuntimeState, LogStatePersistence (Config properties). | Config still: file path, load/validate, status_file_path, "config changed" / mtime. |
| 5 | Coupling | status_server accepts handlers + state + config; no reload_config import. Scheduler/sync use get_sync_state_store(). | sync still imports config (_last_log_position, _config). |
| 6 | Tray vs core | Shared daemon_client, status_protocol, runtime_paths. DaemonState + status_to_display_state. Unified logging_utils. | — |
| 7 | Logging | Core and tray: logging_utils (log_message, log_error, set_config, setup_loggers). | — |
| 8 | Error / exit | main sys.exit(result); crash log in runtime_paths (clear/write/read). | Mixed sys.exit(1)/return 1 elsewhere. |
| 9 | Sync / scheduler | SyncContext + build_sync_context; perform_sync_operations(..., context=ctx). Scheduler takes sync_jobs/run_missed_jobs. | sync still uses get_sync_state_store() and config._config; no injected state writer. |
| 10 | Python 3.14 | pyproject 3.12+; type annotations in status_protocol, runtime_paths; DEV.md free-threading note. | No shared TypedDict for status; globals remain. |
| 11 | "Refactor first" | Paths, daemon client, protocol, main thin, DaemonRuntimeState, SyncStateStore, LogStatePersistence, tray shared DTO + logging, crash log in runtime_paths. | Immutable "loaded config" vs Config not done. Sync state writer injection not done. |
