```bash
python -m venv .venv
# Activate (use one):
source .venv/bin/activate      # Bash/Zsh (Linux/macOS)
source .venv/bin/activate.fish # Fish
# .venv\Scripts\activate       # Windows (cmd/PowerShell)
pip install -e .
```

## How to run

**CLI** (after `pip install -e .`):
- `rclone-bisync-manager daemon start|stop|status|reload` — daemon lifecycle
- `rclone-bisync-manager sync [job ...]` — run sync (optionally `--resync`, `--force-bisync`)
- `rclone-bisync-manager add-sync JOB ...` — queue job(s)

**Global options (CLI):** `--console-log` (log to console), `-d`/`--dry-run`, `--config PATH`

**Tray:** `rclone-bisync-manager-tray`  
Options: `--log-level DEBUG|INFO|WARNING|ERROR|CRITICAL` (default NONE), `--enable-experimental`, `--config PATH`, `--icon-style 1|2`, `--icon-thickness N`

**Debug:** Use `--console-log` for daemon/sync so logs go to stdout; use `--log-level DEBUG` (or INFO) for the tray.

## Pydantic usage

- **Config validation:** `config.py` defines Pydantic v2 models (`ConfigSchema`, `SyncJobConfig`, `OptionsValidatorMixin`) used only for loading and validating YAML + CLI merge. The runtime `Config` class holds the validated `_config` (a `ConfigSchema` instance) and mutable state (paths, log state, args). Schema and runtime are kept separate.
- **Serialization:** `status_server.py` uses `BaseModel` only to detect Pydantic models when building JSON (`.model_dump()`). No Pydantic models are used for status payloads; status is plain dicts.
- **Dependency:** `pydantic>=2.8,<3`; code assumes v2 API (`model_json_schema`, `model_dump`, `Field(ge=..., le=...)`, `field_validator` with `info`).

## Tray state and display (system_tray.py)

**Invariant:** The tray **icon** is painted from `daemon_manager.current_state` (via `get_effective_state_for_icon()`). The **menu** is built from a fresh `get_daemon_status()` each time. So the icon only changes when `current_state` is updated; the menu always reflects the latest status.

**Rule:** Every path that triggers a UI refresh must update `daemon_manager.current_state` (and optionally `update_sync_feedback(status)`) **before** queuing the refresh. Otherwise the next paint uses stale state and the icon stays wrong.

**Where state is set:**
- `status_protocol.status_to_display_state(status, daemon_start_error)` — pure mapping from status dict (or None) to `DaemonState`. Single source of truth for “what state does this status mean?”.
- `daemon_manager.update_state(new_state)` — the only writer for `current_state`. Call this whenever we know the correct state.
- `daemon_manager.get_current_state(status)` — computes state from status; does **not** update stored state. Call `update_state(get_current_state(...))` to persist.

**UI refresh triggers (each must set state before refresh):**
1. **Polling:** `check_status_and_update()` — gets status, `update_sync_feedback()`, `update_state()`, then `update_queue.put(True)`. OK.
2. **Startup:** `run_tray_appindicator()` — after `initial_status`/`initial_state`, calls `update_sync_feedback(initial_status)`, `update_state(initial_state)`, then first `_write_tray_icon_to_path`. OK.
3. **Reload config:** `reload_config()` — on success fetches fresh status and `update_state()`; on all paths (error/exception) fetches status and `update_state()` before `put(True)`. OK.
4. **Add to sync:** `add_to_sync_queue()` — always fetches fresh status, `update_sync_feedback()`/`update_state()`, then `put(True)` (success or failure or exception). OK.
5. **Start daemon:** `start_daemon()` — if already running sets `update_state(RUNNING)`; on failure sets `update_state(FAILED)`; then `put(True)` or uses `update_menu_and_icon()`. OK.
6. **Stop daemon:** On failure calls `update_menu_and_icon()` which fetches status and `update_state()` before `GLib.idle_add(_update_appindicator_ui)`. On success, `_wait_then_refresh` eventually calls `update_menu_and_icon()`. OK.
7. **Manual refresh:** `update_menu_and_icon()` — fetches status, `update_sync_feedback()`, `update_state()`, then `GLib.idle_add(_update_appindicator_ui)`. OK.

**Icon vs menu:** `_update_appindicator_ui()` uses `get_effective_state_for_icon()` for the **icon** (stored state + sync-feedback override) and `get_menu_spec(get_daemon_status())` for the **menu** (fresh status). So adding a new refresh trigger: always update state (and sync feedback if you have status) before `update_queue.put(True)` or `GLib.idle_add(update_menu_and_icon)` / `_update_appindicator_ui`.

## State and status flow (deep audit)

End-to-end: **daemon** produces status; **tray** and **CLI** consume it. The tray also keeps a **display state** (`daemon_manager.current_state`) so the icon can be painted without re-fetching.

### Where status is produced (daemon)

- **status_server.generate_status_report(state, config)** builds the status dict. It uses:
  - **state** (`DaemonRuntimeState`): `running`, `shutting_down`, `in_limbo`, `config_invalid`, `config_error_message`, `currently_syncing`, `queued_paths`. Set in `daemon_functions` (main loop, reload, process_sync_queue) and `daemon_state.DaemonRuntimeState`.
  - **config**: `config_changed_on_disk` (set in `config.check_config_changed()` every second; cleared in `config.reset_config_changed_flag()` — called only **after** successful reload in `daemon_functions.reload_config()` so status never briefly reports “no change” before apply).
  - **get_sync_state_store()**: `sync_errors`; per-job `last_sync`, `next_run`, `sync_status`, `resync_status` from `store.sync_state.get_job_state(key)`. `sync_status`/`resync_status` are normalized by `standardize_status()` (str or dict → str; None → `"NONE"`).
- **config.check_config_changed()**: compares `config_file` mtime; sets `config_changed_on_disk = True` when mtime increases.
- **sync_state_store**: `sync.py` writes `sync_status`/`resync_status`/`last_sync` via `write_status()` and `update_job_state()`; `scheduler` writes `next_run` via `update_job_state()`; store persists to disk.

### Where status is consumed

- **Tray:** `get_daemon_status()` → `request_status()` (daemon_client) → socket STATUS → daemon returns JSON. Tray then uses `status_to_display_state(status)` (status_protocol) to get `DaemonState` and updates `daemon_manager.current_state` before any UI refresh (see “Tray state and display” above).
- **CLI:** `run_daemon_status()` → `print_daemon_status()` → `request_status()` → prints JSON; no `DaemonState` or icon.

### Protocol and keys

- **status_protocol**: single source of key names (`CONFIG_CHANGED_ON_DISK`, `CURRENTLY_SYNCING`, etc.) and `status_to_display_state()`. Order of checks: FAILED → OFFLINE → SHUTTING_DOWN → CURRENTLY_SYNCING → LIMBO → CONFIG_INVALID → SYNC_ISSUES → CONFIG_CHANGED → RUNNING → OFFLINE.
- **daemon_client**: `request_status()` returns parsed dict or None; `request_reload()` returns `{status, message}` or None. Tray uses `sp.STATUS` / `sp.MESSAGE` for reload response.

### Thread and process notes

- **Tray:** Polling thread calls `get_daemon_status()` every second; main thread calls it on user actions (reload, add sync, etc.). Global `last_status` in `get_daemon_status()` is only for “Daemon status changed” logging; the **refresh** decision uses the polling loop’s local `last_status` (previous iteration’s status). So refresh logic is correct; only the log can be interleaved.
- **Daemon:** STATUS/RELOAD/STOP are handled in threads started per connection; RELOAD runs in that thread and updates `config` and `state` in process. So after RELOAD response is sent, the next STATUS from any client sees the new config.

### Invariants to keep

1. **Reload:** Clear `config_changed_on_disk` only **after** successful `load_and_validate_config()` (daemon_functions.reload_config).
2. **Tray:** Every UI refresh path must call `update_state(...)` (and `update_sync_feedback(...)` when status is available) **before** queuing the refresh.
3. **Status report:** When `in_limbo` or `config_invalid`, report omits `CURRENT_CONFIG` and `SYNC_JOBS`; consumers treat missing `SYNC_JOBS` as `{}` (e.g. _has_sync_issues).

## Sync, scheduler, and add-sync flow

### Sync (sync.py, daemon_functions.process_sync_queue)

- **process_sync_queue** (daemon main loop): Pops one (key, force_bisync, force_resync) from `state.sync_queue`, sets `state.currently_syncing = key`, calls `perform_sync_operations(key, ...)`, then clears `state.currently_syncing`. So status report’s `currently_syncing` and `queued_paths` reflect daemon runtime.
- **perform_sync_operations**: Reads `read_status(key)` (sync_state_store), runs resync and/or bisync, calls **write_status** (updates `sync_status`/`resync_status` and always sets `last_sync_times[job_key] = now`) and **store.sync_state.update_job_state(...)** + **store.save()**. So `last_sync` in status is “last attempt” (including failed runs). Sync result (COMPLETED/FAILED) is written via **handle_rclone_exit_code** → **update_sync_error** / **remove_sync_error** (sync_errors dict keyed by local_path).
- **write_status**: No-op when `context.dry_run`; otherwise updates store in-memory and calls **store.save()**. So dry-run never persists state.

### Scheduler (scheduler.py)

- **schedule_tasks(sync_jobs, run_missed_jobs)**: If `run_missed_jobs`, **check_missed_jobs** schedules one run per job (last missed time only; each **schedule_task** replaces any existing task for that key). Then schedules next run per job from cron. **schedule_task** updates **store.sync_state.update_job_state(path_key, next_run=...)** and **store.save()**.
- **check_scheduled_tasks** (daemon loop): Pops tasks whose `scheduled_time <= now`, calls **add_to_sync_queue(path_key)** and schedules next run via cron. So status `next_run` comes from store, which is updated by scheduler.
- **clear_tasks** (on reload): Clears in-memory heap/map only; store’s `next_run` is overwritten by the next **schedule_tasks** call in reload_config.

### Add-sync socket (daemon_functions.handle_add_sync_request, daemon_client.request_add_sync)

- Daemon: Listens on add-sync socket; parses JSON `{job_key, force_bisync?, resync?}`; if job in `config._config.sync_jobs`, sets force_operation/force_resync on the job and calls **add_to_sync_queue(job, ...)**; sends `OK` or error string; **finally** closes connection. So “OK” means request accepted; the job may already be queued or syncing (add_to_sync_queue no-ops in that case).
- Client: **request_add_sync** sends payload, reads until close; returns `"OK"` if response.strip() == `"OK"`, else error string. Tray uses that to refresh state and queue UI update.

### Hash warnings and log state

- **config.hash_warnings** is **config._log_state.hash_warnings** (in-memory dict, job_key → message or None). **build_sync_context** passes the same dict reference into **context.log_state.hash_warnings**. **check_for_hash_warnings** (sync.py) updates **context.log_state.hash_warnings[key]** (and last_log_position). So the daemon’s config hash_warnings is updated in place; **generate_status_report** uses **getattr(c, "hash_warnings", {})** and **hash_warnings.get(key, False)** for status. So SYNC_ISSUES can be driven by per-job hash_warnings (truthy = issue).

### Status window (tray)

- **_show_status_window_gtk** uses **get_daemon_status()** and **daemon_manager.get_current_state(status)**. If OFFLINE/FAILED it shows “Daemon is not running” and start button; else it shows General / Sync Jobs / Sync Errors / Config tabs. All uses of **status** in the “else” branch are **status.get(...)**; if status were ever non-dict we’d avoid the else branch (get_current_state(None) is OFFLINE). Defensive: treat status as dict in else (e.g. `status = status if isinstance(status, dict) else {}`) so no attribute errors on malformed response.

## Architecture notes (Python 3.14 / free-threading)

The current design uses global mutable state (e.g. `config`, `scheduler`, `get_sync_state_store()`) and module-level locks. Moving toward injected services and less global state would make it easier to adopt free-threading (PEP 779) or run the daemon loop and status server in a free-threaded environment later.