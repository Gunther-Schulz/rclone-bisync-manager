# TODO

## Known Issues

- [x] **Status JSON decode with many sync_jobs:** Previously ">3 sync_jobs" caused JSON decode (truncated response). **Verified fixed:** STATUS client uses `_recv_all()` so full response is read; no truncation. Very large payload could still cause timeout or memory use (see Issues and hardening).
- [ ] **Tray shows "Daemon Offline" when daemon runs:** **Mitigated.** Flow unchanged; causes: startup race, daemon busy, or transient failure. **Implemented:** Status timeout 8s, retries (2 × 0.3s), and sticky OFFLINE (only after 2 consecutive None polls) so transient failures don't flicker to Offline.
- [ ] **Stopping daemon not reliable during RUNNING:** **Mitigated.** **Implemented:** Tray uses retries for `request_stop`; only logs "Daemon is shutting down" and runs wait-for-gone when STOP returns success; on failure shows "Stop failed" notification and logs error; always calls `update_menu_and_icon()` so UI reflects actual state.
- [ ] **Tray does not reliably show RUNNING (status window does):** **Mitigated.** Same root cause; **implemented:** longer status timeout (8s), retries, and sticky OFFLINE (2 consecutive None) reduce spurious Offline.

## Testing

- [ ] Test if missed runs are still processed
- [ ] Test behavior when suspending the PC
- [ ] Test per-sync job options override
- [ ] Verify exclude rule file changes trigger a resync

### Automated tests (for beta)

- [x] **Unit:** `env_helpers.env_dir` (unset, empty, whitespace, normal value)
- [x] **Unit:** Config schema validation (valid minimal, invalid cron, disallowed keys in options)
- [x] **Unit:** Scheduler `check_missed_jobs` / `schedule_tasks` (with patched store; run_missed_jobs True/False, missed not overwritten)
- [x] **Unit:** SyncStateStore load/save roundtrip, empty/invalid JSON; SyncState get_job_state
- [x] **Unit:** status_protocol _has_sync_issues, status_to_display_state
- [x] **Integration:** Status server response shape (version, pid, running) with minimal state; standardize_status
- [x] **Unit:** runtime_paths path suffixes; write/read/clear crash log (patched path)
- [x] **Unit:** sync handle_rclone_exit_code (COMPLETED/FAILED, error recording)
- [x] **Unit:** utils calculate_md5
- [ ] **Manual / e2e:** Missed runs, suspend, per-job overrides, exclude-file resync (keep in Testing above)

## Beta readiness (checklist)

To move from alpha to beta:

1. **Tests:** Add at least a small automated test suite (see “Automated tests” above). Pytest + `tests/` with a few unit tests is enough to catch regressions.
2. **README:** Change “not yet recommended for production” to a beta disclaimer (e.g. “Beta — suitable for production use with backups; please report bugs”).
3. **Version/classifier:** Bump to `0.3.0b1` (or `0.2.0b1`); set PyPI classifier to `Development Status :: 4 - Beta`.
4. **Optional:** CHANGELOG or release notes for the first beta tag; document known limitations (e.g. tray/stop mitigations in Known Issues).

## Development

- [ ] Implement internal Python CPU limiter
- [ ] Implement separate filter files per job

## Improvements

- [ ] Refactor code to eliminate 'global' keyword (if possible)

### Logging improvement (rotation + config)

- [x] **log_file_path from YAML ignored:** Config wrapper’s `log_file_path` was never updated from `_config` after load. **Fixed:** In `config.load_and_validate_config()`, after successful validation we set `self.log_file_path = self._config.log_file_path` so `logging_utils` and callers use the path from `config.yaml`.
- [x] **Step 1 — Log rotation:** Add stdlib `RotatingFileHandler` in `logging_utils` (maxBytes=5MB, backupCount=5); keep public API (`log_message`, `log_error`, `set_config`, `setup_loggers`, `ensure_log_file_path`). Daemon/tray use `config.log_file_path` (synced from YAML).
- [x] **Step 2 — Optional YAML for rotation:** Optional config fields so users can tune rotation without code change.
  - **Schema:** `ConfigSchema` has `log_rotation_max_mb`, `log_rotation_backup_count` (Optional[int] = None). Defaults in code when None: 5 MB, 5.
  - **Config wrapper:** Synced from `_config` after load; initialized to None in `_init_logging_paths`.
  - **logging_utils:** `_get_rotation_params()` reads config; `RotatingFileHandler` uses those or defaults.
  - **Config editor:** `GENERAL_FIELDS` + `GENERAL_TOOLTIPS`; optional ints as Entry; `build_config_from_widgets` uses `_parse_optional_int`.
  - **Example YAML:** Commented optional entries in `examples/config.yaml.example`.

## Issues and hardening

- [x] **Socket leak in daemon_client:** Client sockets were not closed on exception (connect/send/recv/json). Fixed: `try`/`finally` so socket is always closed.
- [x] **Known UX/robustness (tray):** "Daemon Offline" when daemon runs; stop not reliable during RUNNING; tray does not reliably show RUNNING. **Implemented:** Status timeout 8s + retries; sticky OFFLINE (2 consecutive None); stop_daemon only shows "shutting down" on success, wait-for-daemon-gone (poll every 2s up to 12s), "Stop failed" notification + log on failure; always refresh UI after stop attempt.
- [ ] **Status payload size:** **Verified:** STATUS and GET_CONFIG use `_recv_all()` in daemon_client — no truncation, so the old ">3 sync_jobs" JSON decode from single recv is fixed. Remaining risk: very large payload (many/large jobs) can cause long receive time (timeout) or high memory. Options: slim STATUS (omit/truncate `current_config` or per-job details), or document practical limit.
- [x] **Atomic write for sync_state.json / sync_errors.json:** Write to `.tmp` then `os.replace()` in `sync_state_store.py` to avoid corruption on crash. **Done.**
- [x] **Optional retry for STOP/status when daemon busy:** `request_status(timeout=5, retries=0, retry_delay=0.5)` and `request_stop(...)` support optional retries. Tray uses `retries=2`, `retry_delay=0.3`. **Done.**

## Refactor plan — status (done vs left)

### Tray: use modern AppIndicator / SNI path (GNOME-native) — DONE

- **Done:** Tray tries **AppIndicator3** (SNI) via **PyGObject** first; icon shows with “AppIndicator and KStatusNotifierItem Support” on stock GNOME. No fallback; requires **AppIndicator**. If unavailable, `gi.repository.AppIndicator3` is unavailable (e.g. missing libappindicator3).
- **System deps (for AppIndicator):** `libappindicator3-1`, `gir1.2-appindicator3-0.1` (or equivalent). Python deps: PyGObject (already in tray extras).
- **Notes:** AppIndicator path uses libnotify for notifications; status window, config editor, and “Show Full Error” use GTK. Single path: GTK for status window, config editor, Show Full Error; libnotify for notifications.

The bullets below describe the original issues; the table "Refactor status: what's done vs left" is the source of truth for what has been done and what remains.

1. Global state and “God” objects
config in config.py is a global singleton. Almost every module imports and uses it (300+ references). It holds:
File paths, validated schema, CLI args
Runtime daemon state (running, shutting_down, in_limbo, currently_syncing, sync_queue, etc.)
Sync state persistence (save/load sync_state, sync_errors)
Lock paths, cache dirs, hash_warnings, etc.
sync_state is another global (module-level instance) mutated from config, scheduler, and sync.
scheduler is a global singleton in scheduler.py.
logger / config in logging_utils are global and set from outside (set_config(cfg)).
So: one “config” object is both “configuration + runtime daemon state + persistence.” That makes behavior hard to reason about and test, and creates hidden coupling.
2. main.py: orchestration, duplication, and mixed concerns
Orchestration is inline in main(): parse args → load config → big if/elif on args.command (daemon start/stop/status/reload, sync, add-sync). That’s both “wire-up” and “business” in one place.
Socket use is duplicated: status socket path and connect/send/recv logic for “reload” and “add-sync” live in main.py and again in daemon_functions.py, status_server.py, system_tray.py, config_editor.py. Same for lock path in config.py and utils.py.
Daemon startup mixes many concerns in one block: env check, lock file, DaemonContext, signal map, then daemon_main(). No clear separation between “bootstrap,” “daemonize,” and “run daemon loop.”
Refactor direction: extract a small “application” or “commands” layer that receives parsed args and config, and delegates to daemon/sync/add-sync handlers; share one place for socket paths and client helpers.
3. Hardcoded paths and no single “runtime environment”
/tmp/rclone_bisync_manager_status.sock, /tmp/rclone_bisync_manager_add_sync.sock, /tmp/rclone_bisync_manager.lock, /tmp/rclone_bisync_manager_crash.log appear in multiple files.
XDG dirs are used for config/cache/state, but /tmp is hardcoded. No abstraction for “where does this process put sockets/locks/crash logs?” (e.g. one RuntimePaths or env object).
That makes testing and alternate installs (e.g. per-user or container) harder and will keep causing small inconsistencies.
4. Config class doing too much
Config handles: default paths, config file path, loading/validating YAML, merging CLI args, validation errors, status file paths per job, (Done: sync_state/sync_errors → SyncStateStore; daemon flags → DaemonRuntimeState.) Remaining on Config: “config changed on disk” and mtime; hash_warnings, _last_log_position, status_file_path.
Pydantic is used for schema and validation, but the mutable runtime and file I/O live in the same object. So “configuration” and “process state” are fused.
Splitting “immutable config (from file + CLI)” from “daemon runtime state” and “persistence (sync state, errors)” would clarify boundaries and make testing easier.
5. Tight coupling and circular risk
status_server does not import daemon_functions; it accepts an optional handlers dict (e.g. RELOAD → reload_config). The daemon passes handlers when starting the server, so there is no circular import.
scheduler imports config and get_sync_state_store(); uses store.sync_state and store.save() (no longer config.save_sync_state()).
sync reads/writes config._config, config.hash_warnings, config._last_log_position; sync_state and sync_errors via get_sync_state_store().
daemon_functions drives the loop and calls scheduler, sync, config, and status server.
So: config/sync_state/scheduler/sync/daemon_functions/status_server form one tightly coupled cluster. There’s no clear “core domain” that doesn’t depend on a giant config object.
6. Tray vs core duplication and protocol
system_tray reimplements: daemon state (e.g. DaemonState enum), “get status via socket,” “reload,” “stop,” “add to sync queue,” crash log path, and its own log_message and argument handling.
The status protocol (STATUS, RELOAD, STOP, GET_CONFIG, and JSON shape) is not defined in one place; status_server builds the payload and tray (and CLI) assume that shape. So the “API” is implicit.
Refactor direction: shared constants for socket paths and command strings; one small “daemon client” (or “status client”) used by CLI and tray; optionally a shared “daemon state” or status DTO used by tray and status_server.
7. Logging split and inconsistency
Core uses logging_utils: log_message, log_error, set_config(cfg) so the logger can read config (e.g. console_log). Logger is global.
Tray uses stdlib logging and its own log_message that looks at tray args. So two different logging models for “same” process family.
Unifying behind one logging approach (e.g. stdlib logging with a single configuration point for both daemon and tray) would simplify behavior and debugging.
8. Error handling and exit paths
Some code uses sys.exit(1) or exit(1) (e.g. in main, utils); other code returns or raises. No consistent “application result” or “exit code” strategy.
Daemon crash is written to /tmp/...crash.log and tray reads it; that’s fine, but the “who is responsible for creating/cleaning this file?” is spread across daemon_functions and system_tray.
Centralizing “fatal error” handling and “where to write crash info” would make behavior clearer.
9. Sync and scheduler
sync.py: perform_sync_operations does resync/bisync, status file read/write, sync_state via get_sync_state_store() and store.save(); It also reaches into config._config and config._last_log_position and hash_warnings. So “run one sync” is mixed with “global config and state.”
scheduler uses config._config and get_sync_state_store() (store.sync_state, store.save()). So scheduling is tied to the same global state.
Extracting a “sync runner” that takes “job config + options” and “state writer” (interface or callback) would make sync testable without the full config/sync_state globals.
10. Python 3.14–relevant points
Requires 3.12+: You’re already on 3.12; 3.14 is mostly additive.
Annotations: PEP 649/749 (deferred annotation evaluation) means you can use forward references and heavier typing without strings; good time to add proper type hints and maybe a shared types or protocols module for “Config”, “SyncJob”, “StatusPayload”, etc.
Deprecations: Check for argparse.BooleanOptionalAction usage and any use of the deprecated AST nodes (unlikely in app code). No need to use asyncio child watchers or the other removed bits if you’re not using them.
Free-threaded (PEP 779): If you ever move the daemon loop or status server to free-threaded, the current heavy use of global mutable state and locks will be a liability. Moving toward “injected services” and less global state will help if you adopt free-threading later.
stdlib: No need to change immediately, but pathlib and importlib.resources are the preferred way to handle paths and resources; you already use Path in status_server; extending that elsewhere (and avoiding deprecated importlib.abc resource APIs) aligns with 3.14.
So: no need to rewrite for 3.14, but cleaning globals, adding types, and centralizing paths/protocol will make a 3.14 (and free-threaded) future easier.
11. What to refactor first (if you want a short list)
Paths and “runtime environment”: One place (e.g. a small module or dataclass) for all socket paths, lock path, crash log path, and optionally XDG base dirs; use it from main, daemon_functions, status_server, tray, config_editor, utils.
Split “config”: Separate (a) “loaded config” (read-only after load), (b) “daemon runtime state” (running, shutting_down, queue, currently_syncing, etc.), (c) “sync state persistence” (sync_state + sync_errors). Then inject these where needed instead of one global config.
Daemon client / status protocol: Shared constants and one “daemon client” (status, reload, stop, add-sync) used by main and tray; status_server is the single place that implements the protocol.
main.py: Thin entrypoint that parses args, builds “environment” and “config,” and dispatches to command handlers (daemon start/stop/status, sync, add-sync); move socket/lock logic into those handlers or the shared client.
Tray: Use the shared daemon client and paths; consider reusing core logging and, if useful, a small shared “status/state” type instead of re-deriving everything in the tray.
Sync + scheduler: Introduce a narrow interface for “run this job” and “persist sync state” so sync and scheduler don’t depend on the giant config/sync_state globals; then add types and annotations with 3.14 in mind.
That’s the picture: one big global “config,” duplicated paths and protocol, mixed concerns in main and config, and tray reimplementing core behavior. Fixing paths and splitting config/state will give the biggest leverage; the rest can follow step by step.

**Source of truth for done vs left:** The table below. The bullets above describe the original issues; the table reflects what has been implemented and what remains.

---

### Refactor status: what's done vs left

| # | Topic | Done | Left |
|---|--------|------|------|
| 1 | Global state / God objects | Daemon runtime → `DaemonRuntimeState` (daemon_state.py). Sync persistence → `SyncStateStore` (sync_state_store.py). | `config` still a global singleton (80+ refs). Holds paths, schema, CLI merge, status paths, hash_warnings, _last_log_position. scheduler/logger still global. |
| 2 | main.py / orchestration | Thin main: parse args → load config → `run_command(args, config)`. Commands layer in commands.py; socket/lock in daemon_client + runtime_paths. Daemon startup: phase comments (Bootstrap / Acquire start lock / Daemonize / Run loop) in run_daemon_start; daemon_main phases + `_run_main_loop(state, status_thread)`; child exits with sys.exit(1) on lock/config failure. | — |
| 3 | Hardcoded paths | `runtime_paths.py`: single place for status socket, add_sync socket, lock file, crash log. Env override: `RCLONE_BISYNC_MANAGER_RUNTIME_DIR` or `XDG_RUNTIME_DIR`, fallback `/tmp`. Used by daemon_client, status_server, daemon_functions, utils, commands, tray. | — |
| 4 | Config class | Sync state/errors → SyncStateStore. Daemon flags → DaemonRuntimeState. Log state (_last_log_position, hash_warnings) → LogStatePersistence (Config owns one; properties delegate). | Config still has: config file path, load/validate, status_file_path, "config changed" / mtime. Fused with process state. |
| 5 | Tight coupling | status_server accepts handlers + state + config; daemon passes DaemonRuntimeState and handlers (e.g. RELOAD); no reload_config import in status_server. Scheduler/sync use get_sync_state_store(). | sync still imports config (write-back _last_log_position, read _config for status). No clear "core domain" without config. |
| 6 | Tray vs core | Shared `daemon_client`, `status_protocol` (sp.*), runtime_paths (crash log). Shared `DaemonState` enum and `status_to_display_state()` in status_protocol; tray uses them. Tray uses logging_utils (unified logging). | — |
| 7 | Logging | Core and tray: logging_utils (log_message, log_error, set_config, setup_loggers). Single configuration point for daemon and tray. | — |
| 8 | Error handling / exit | main uses sys.exit(result); commands return 0/1. Crash log: single owner in runtime_paths (clear_crash_log, write_crash_log, read_crash_log); daemon_functions writes/clears, tray reads. | Mixed use of sys.exit(1), exit(1), return 1 elsewhere. |
| 9 | Sync and scheduler | `SyncContext` + `build_sync_context()`; perform_sync_operations(key, ..., context=ctx). Scheduler takes sync_jobs/run_missed_jobs as args. Log state write-back via Config properties (LogStatePersistence). | sync still uses get_sync_state_store() and config._config. No injected state writer; scheduler still uses config._config. |
| 10 | Python 3.14 | pyproject 3.12+; no deprecated AST. status_protocol: type annotations (_has_sync_issues, status_to_display_state). runtime_paths: pathlib.Path for path construction, str return. DEV.md: free-threading note. | No shared TypedDict for status payload; globals remain for free-threading. |
| 11 | "Refactor first" checklist | **Paths:** runtime_paths in place, env override, used everywhere. **Daemon client / protocol:** daemon_client + status_protocol used by CLI and tray. **main:** thin; commands.py dispatches. **Daemon startup:** phase comments + _run_main_loop; child sys.exit(1) on lock/config failure. **Split config:** DaemonRuntimeState + SyncStateStore done; LogStatePersistence for _last_log_position + hash_warnings (Config properties). **Tray:** shared DaemonState + status_to_display_state; unified logging_utils. **Crash log:** owned by runtime_paths. | **Split config (cont'd):** Immutable "loaded config" vs Config not done. **Sync + scheduler:** inject state writer / SyncStateStore not done; types/protocols not added. |



1	#3, #8 (crash log)	Runtime paths + crash log ownership — **DONE**
2	#2	Daemon startup structure — **DONE**
3	#6, #7	Tray shared DTO + unified logging — **DONE**
4	#4, #5, #9	Config slim-down + injection + sync state writer — **DONE** (minimal: LogStatePersistence)
5	#10	Types/protocols, pathlib, free-threading notes — **DONE**