# TODO

## Development

- [ ] **Postponed:** Implement separate filter files per job.
- [ ] **False ERROR on every shutdown:** `Error handling client request: [Errno 9] Bad file descriptor` follows "Daemon shutdown complete" in all 9 occurrences in the logs since 2026-08-04 (`grep -B1` over rclone-bisync-manager.log*). Likely cause (from code, not reproduced): the server loop's cleanup (`status_server.py:77-83`) closes `active_connections` while a `handle_client` thread, e.g. the tray's STATUS poll, is still between `recv` and `sendall` (`:105`/`:133`), and `:141-142` logs the EBADF as ERROR. Harmless (the daemon is exiting), but an ERROR line on a non-defect trains people to ignore the log. Fix: during shutdown, call `conn.shutdown(SHUT_RDWR)` instead of closing a connection a handler still owns, or treat OSError while `shutting_down` as INFO. Verifier: a test that stops the server while a handler is mid-request produces no ERROR line. Ships with the next release; not worth a release on its own.
- [x] **Tray status refactor:** Single source of truth for icon/menu; paint from poll thread’s stored status only (no UI re-fetch). `_get_status_path`, status window on open, and `start_daemon` “already running” now use `state.last_status` under lock. `get_daemon_status()` only used at startup to populate `last_status`.

---

## Status server / payload architecture

Current behavior: every STATUS response includes full `current_config` (entire config schema) and full per-job definitions (local, remote, schedule, rclone_options, etc.) plus runtime state. For typical configs this is fine; the README note may overstate the risk.

**Better architecture (no code yet)**

- [ ] **Status = runtime only:** Change STATUS response so it does **not** include full config or full job definitions. Include only: version, pid, running, shutting_down, in_limbo, config_invalid, config_error_message, currently_syncing, queued_paths, config_file path, log_file path, sync_errors; and per job **only** last_sync, next_run, sync_status, resync_status, hash_warnings (no local/remote/schedule/options). Payload size then largely independent of config size.
- [ ] **Full config elsewhere:** Tray/CLI get full config when needed from: (a) config file path (client reads from disk), or (b) existing GET_CONFIG request. Status window / config editor use that; polling stays small.
- [ ] **Server:** In `generate_status_report`, stop setting `status[sp.CURRENT_CONFIG]` and stop putting `model_to_dict(value)` (full job) into `status[sp.SYNC_JOBS][key]`; only add per-job runtime fields (last_sync, next_run, sync_status, resync_status, hash_warnings). Job keys/list can stay so client knows which jobs exist.
- [ ] **Tray/CLI:** Where status is consumed, stop relying on status for job names/labels or full config; use config file or GET_CONFIG for display/editing. Verify status window, menu, and `daemon status` still have what they need (paths and runtime state from STATUS; details from config).

