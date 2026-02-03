# TODO

## Development

- [ ] **Postponed:** Implement separate filter files per job.
- [ ] **Tray status refactor (planned):** Single source of truth for icon/menu; paint from poll thread’s stored status only (no UI re-fetch). Currently the icon uses `state.last_status`, but status window (line ~981), `_get_status_path` (~1161), and some menu paths (~766) still call `get_daemon_status()` (blocking re-fetch). Refactor: use `state.last_status` (under lock) for all UI; only the poll loop updates it.

---

## Status server / payload architecture

Current behavior: every STATUS response includes full `current_config` (entire config schema) and full per-job definitions (local, remote, schedule, rclone_options, etc.) plus runtime state. For typical configs this is fine; the README note may overstate the risk.

**Better architecture (no code yet)**

- [ ] **Status = runtime only:** Change STATUS response so it does **not** include full config or full job definitions. Include only: version, pid, running, shutting_down, in_limbo, config_invalid, config_error_message, currently_syncing, queued_paths, config_file path, log_file path, sync_errors; and per job **only** last_sync, next_run, sync_status, resync_status, hash_warnings (no local/remote/schedule/options). Payload size then largely independent of config size.
- [ ] **Full config elsewhere:** Tray/CLI get full config when needed from: (a) config file path (client reads from disk), or (b) existing GET_CONFIG request. Status window / config editor use that; polling stays small.
- [ ] **Server:** In `generate_status_report`, stop setting `status[sp.CURRENT_CONFIG]` and stop putting `model_to_dict(value)` (full job) into `status[sp.SYNC_JOBS][key]`; only add per-job runtime fields (last_sync, next_run, sync_status, resync_status, hash_warnings). Job keys/list can stay so client knows which jobs exist.
- [ ] **Tray/CLI:** Where status is consumed, stop relying on status for job names/labels or full config; use config file or GET_CONFIG for display/editing. Verify status window, menu, and `daemon status` still have what they need (paths and runtime state from STATUS; details from config).

