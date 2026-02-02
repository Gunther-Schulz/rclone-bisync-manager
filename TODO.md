# TODO

## Known Issues

- [ ] More than 3 sync_jobs will cause `JSON decode error: Expecting ',' delimiter: line 1 column 4089 (char 4088)` returned by the status command. - fixed by removing config objects from the status
- [ ] The tray displays "Daemon Offline" even when the daemon is running in the state described in the last point above.
- [ ] Stopping the dameon does not reliably work during tray status RUNNING
- [ ] The tray does not reliably display the RUNNING status. It's status window does however.

## Testing

- [ ] Test if missed runs are still processed
- [ ] Test behavior when suspending the PC
- [ ] Test per-sync job options override
- [ ] Verify exclude rule file changes trigger a resync

## Development

- [ ] Implement internal Python CPU limiter
- [ ] Implement separate filter files per job

## Improvements

- [ ] Refactor code to eliminate 'global' keyword (if possible)

## Refactor plan — status (done vs left)

### Tray: use modern AppIndicator / SNI path (GNOME-native) — DONE

- **Done:** Tray tries **AppIndicator3** (SNI) via **PyGObject** first; icon shows with “AppIndicator and KStatusNotifierItem Support” on stock GNOME. No fallback; requires **AppIndicator**. If unavailable, `gi.repository.AppIndicator3` is unavailable (e.g. missing libappindicator3).
- **System deps (for AppIndicator):** `libappindicator3-1`, `gir1.2-appindicator3-0.1` (or equivalent). Python deps: PyGObject (already in tray extras).
- **Notes:** AppIndicator path uses libnotify for notifications; status window, config editor, and “Show Full Error” use GTK. Single path: GTK for status window, config editor, Show Full Error; libnotify for notifications.

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
status_server imports reload_config from daemon_functions inside handle_client to avoid a top-level cycle. So “status server” knows about “daemon reload” implementation.
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

---

### Refactor status: what's done vs left

| # | Topic | Done | Left |
|---|--------|------|------|
| 1 | Global state / God objects | Daemon runtime → `DaemonRuntimeState` (daemon_state.py). Sync persistence → `SyncStateStore` (sync_state_store.py). | `config` still a global singleton (80+ refs). Holds paths, schema, CLI merge, status paths, hash_warnings, _last_log_position. scheduler/logger still global. |
| 2 | main.py / orchestration | Thin main: parse args → load config → `run_command(args, config)`. Commands layer in commands.py; socket/lock in daemon_client + runtime_paths. | Daemon startup still one block (bootstrap + DaemonContext + daemon_main); could split "bootstrap" vs "daemonize" vs "loop." |
| 3 | Hardcoded paths | `runtime_paths.py`: single place for status socket, add_sync socket, lock file, crash log. Used by daemon_client, status_server, daemon_functions, utils, commands, tray. | Paths still fixed under `/tmp`; no env override or XDG-style runtime base yet. |
| 4 | Config class | Sync state/errors → SyncStateStore. Daemon flags (running, queue, in_limbo, etc.) → DaemonRuntimeState; status_server gets state from that. | Config still has: config file path, load/validate, status_file_path, hash_warnings, _last_log_position, "config changed" / mtime. Fused with process state. |
| 5 | Tight coupling | status_server accepts handlers + state + config; daemon passes DaemonRuntimeState. Scheduler/sync use get_sync_state_store(). | status_server still imports reload_config inside handle_client. sync still imports config (write-back _last_log_position, read _config for status). No clear "core domain" without config. |
| 6 | Tray vs core | Shared `daemon_client` (request_status, request_reload, request_stop, request_add_sync, request_config_schema). Shared `status_protocol` (sp.*) for JSON keys. Tray uses runtime_paths (crash log). | Tray still has its own DaemonState enum and log_message/args; no shared status DTO. |
| 7 | Logging | Core: logging_utils (log_message, log_error, set_config). | Tray uses stdlib logging + its own log_message; two logging models. |
| 8 | Error handling / exit | main uses sys.exit(result); commands return 0/1. | Mixed use of sys.exit(1), exit(1), return 1; crash log ownership spread (daemon_functions write, tray read). |
| 9 | Sync and scheduler | `SyncContext` + `build_sync_context()`; perform_sync_operations(key, ..., context=ctx). Scheduler takes sync_jobs/run_missed_jobs as args. | sync still uses get_sync_state_store() and config (hash_warnings, _last_log_position write-back). No "state writer" interface; scheduler still uses config._config. |
| 10 | Python 3.14 | pyproject 3.12+; no deprecated AST. | No shared types/protocols module; pathlib only in status_server; globals remain for free-threading. |
| 11 | "Refactor first" checklist | **Paths:** runtime_paths in place, used everywhere. **Daemon client / protocol:** daemon_client + status_protocol used by CLI and tray. **main:** thin; commands.py dispatches. **Split config:** DaemonRuntimeState + SyncStateStore done; Config still heavy. | **Split config (cont'd):** Immutable "loaded config" vs Config not done. **Tray:** still re-derives state (DaemonState enum); could use shared status DTO. **Sync + scheduler:** narrow "run this job" + state writer interface not done; types/protocols not added. |