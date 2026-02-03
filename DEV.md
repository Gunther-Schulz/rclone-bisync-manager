~/dev/Gunther-Schulz/rclone-bisync-manager main ⇡ 3m 29s
.venv ❯ rclone-bisync-manager-tray --log-level DEBUG
INFO: Starting daemon
INFO: Attempting to start daemon
INFO: Daemon status changed
INFO: New status: {"version": "0.2.0a1", "pid": 669231, "running": true, "shutting_down": false, "in_limbo": false, "c...
INFO: Status or state changed. Updating menu and icon.
INFO: New status: {'version': '0.2.0a1', 'pid': 669231, 'running': True, 'shutting_down': False, 'in_limbo': False, 'config_invalid': False, 'config_error_message': None, 'currently_syncing': None, 'queued_paths': ['pbs-private', 'pbs-public'], 'config_changed_on_disk': False, 'config_file_location': '/home/g/.config/rclone-bisync-manager/config.yaml', 'log_file_location': '/home/g/.local/state/rclone-bisync-manager/logs/rclone-bisync-manager.log', 'sync_errors': {}, 'current_config': {'rclone_options': {'recover': None, 'resilient': None, 'max_delete': 5, 'log_level': 'INFO', 'max_lock': '15m', 'retries': 3, 'low_level_retries': 10, 'compare': 'size,modtime,checksum', 'create_empty_src_dirs': None, 'check_access': None, 'exclude': ['*.tmp', '*.log', '._*', '.DS_Store', '.Spotlight-V100/**', '.Trashes/**', '.fseventsd/**', '.AppleDouble/**', '.VolumeIcon.icns']}, 'bisync_options': {'conflict_resolve': 'newer', 'conflict_loser': 'num', 'conflict_suffix': 'rc-conflict', 'track_renames': None}, 'resync_options': {'error_on_no_transfer': None}, 'local_base_path': '/mnt/data2t/hidrive', 'exclusion_rules_file': '/mnt/data2t/hidrive/filter.txt', 'max_cpu_usage_percent': 50, 'redirect_rclone_log_output': True, 'run_missed_jobs': True, 'run_initial_sync_on_startup': False, 'sync_jobs': {'pbs-public': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'Öffentlich Planungsbüro Schulz', 'rclone_remote': 'pbs', 'remote': 'Öffentlich Planungsbüro Schulz', 'schedule': '*/30 * * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False}, 'pbs-private': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'ProjektePrivat', 'rclone_remote': 'pbs', 'remote': 'users/pb-schulz/ProjektePrivat', 'schedule': '*/30 * * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False}, 'pbs-software': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'Software', 'rclone_remote': 'pbs', 'remote': 'users/pb-schulz/Software', 'schedule': '0 0 * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False}, 'gunther': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'gunther', 'rclone_remote': 'gunther', 'remote': 'users/gunther', 'schedule': '0 0 * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False}}, 'dry_run': False, 'log_file_path': '/home/g/.local/state/rclone-bisync-manager/logs/rclone-bisync-manager.log', 'log_rotation_max_mb': 5, 'log_rotation_backup_count': 5}, 'sync_jobs': {'pbs-public': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'Öffentlich Planungsbüro Schulz', 'rclone_remote': 'pbs', 'remote': 'Öffentlich Planungsbüro Schulz', 'schedule': '*/30 * * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False, 'last_sync': '2026-02-03T17:09:58.628820', 'next_run': '2026-02-03T18:00:00', 'sync_status': 'COMPLETED', 'resync_status': 'COMPLETED', 'hash_warnings': False}, 'pbs-private': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'ProjektePrivat', 'rclone_remote': 'pbs', 'remote': 'users/pb-schulz/ProjektePrivat', 'schedule': '*/30 * * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False, 'last_sync': '2026-02-03T17:10:22.214174', 'next_run': '2026-02-03T18:00:00', 'sync_status': 'COMPLETED', 'resync_status': 'COMPLETED', 'hash_warnings': False}, 'pbs-software': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'Software', 'rclone_remote': 'pbs', 'remote': 'users/pb-schulz/Software', 'schedule': '0 0 * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False, 'last_sync': '2026-02-03T12:22:39.203361', 'next_run': '2026-02-04T00:00:00', 'sync_status': 'COMPLETED', 'resync_status': 'COMPLETED', 'hash_warnings': False}, 'gunther': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'gunther', 'rclone_remote': 'gunther', 'remote': 'users/gunther', 'schedule': '0 0 * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False, 'last_sync': '2026-02-03T12:32:23.933408', 'next_run': '2026-02-04T00:00:00', 'sync_status': 'COMPLETED', 'resync_status': 'COMPLETED', 'hash_warnings': False}}}
INFO: Daemon status changed
INFO: New status: {"version": "0.2.0a1", "pid": 669231, "running": true, "shutting_down": false, "in_limbo": false, "c...
INFO: Status or state changed. Updating menu and icon.
INFO: New status: {'version': '0.2.0a1', 'pid': 669231, 'running': True, 'shutting_down': False, 'in_limbo': False, 'config_invalid': False, 'config_error_message': None, 'currently_syncing': 'pbs-public', 'queued_paths': ['pbs-private'], 'config_changed_on_disk': False, 'config_file_location': '/home/g/.config/rclone-bisync-manager/config.yaml', 'log_file_location': '/home/g/.local/state/rclone-bisync-manager/logs/rclone-bisync-manager.log', 'sync_errors': {}, 'current_config': {'rclone_options': {'recover': None, 'resilient': None, 'max_delete': 5, 'log_level': 'INFO', 'max_lock': '15m', 'retries': 3, 'low_level_retries': 10, 'compare': 'size,modtime,checksum', 'create_empty_src_dirs': None, 'check_access': None, 'exclude': ['*.tmp', '*.log', '._*', '.DS_Store', '.Spotlight-V100/**', '.Trashes/**', '.fseventsd/**', '.AppleDouble/**', '.VolumeIcon.icns']}, 'bisync_options': {'conflict_resolve': 'newer', 'conflict_loser': 'num', 'conflict_suffix': 'rc-conflict', 'track_renames': None}, 'resync_options': {'error_on_no_transfer': None}, 'local_base_path': '/mnt/data2t/hidrive', 'exclusion_rules_file': '/mnt/data2t/hidrive/filter.txt', 'max_cpu_usage_percent': 50, 'redirect_rclone_log_output': True, 'run_missed_jobs': True, 'run_initial_sync_on_startup': False, 'sync_jobs': {'pbs-public': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'Öffentlich Planungsbüro Schulz', 'rclone_remote': 'pbs', 'remote': 'Öffentlich Planungsbüro Schulz', 'schedule': '*/30 * * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False}, 'pbs-private': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'ProjektePrivat', 'rclone_remote': 'pbs', 'remote': 'users/pb-schulz/ProjektePrivat', 'schedule': '*/30 * * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False}, 'pbs-software': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'Software', 'rclone_remote': 'pbs', 'remote': 'users/pb-schulz/Software', 'schedule': '0 0 * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False}, 'gunther': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'gunther', 'rclone_remote': 'gunther', 'remote': 'users/gunther', 'schedule': '0 0 * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False}}, 'dry_run': False, 'log_file_path': '/home/g/.local/state/rclone-bisync-manager/logs/rclone-bisync-manager.log', 'log_rotation_max_mb': 5, 'log_rotation_backup_count': 5}, 'sync_jobs': {'pbs-public': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'Öffentlich Planungsbüro Schulz', 'rclone_remote': 'pbs', 'remote': 'Öffentlich Planungsbüro Schulz', 'schedule': '*/30 * * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False, 'last_sync': '2026-02-03T17:09:58.628820', 'next_run': '2026-02-03T18:00:00', 'sync_status': 'COMPLETED', 'resync_status': 'COMPLETED', 'hash_warnings': False}, 'pbs-private': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'ProjektePrivat', 'rclone_remote': 'pbs', 'remote': 'users/pb-schulz/ProjektePrivat', 'schedule': '*/30 * * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False, 'last_sync': '2026-02-03T17:10:22.214174', 'next_run': '2026-02-03T18:00:00', 'sync_status': 'COMPLETED', 'resync_status': 'COMPLETED', 'hash_warnings': False}, 'pbs-software': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'Software', 'rclone_remote': 'pbs', 'remote': 'users/pb-schulz/Software', 'schedule': '0 0 * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False, 'last_sync': '2026-02-03T12:22:39.203361', 'next_run': '2026-02-04T00:00:00', 'sync_status': 'COMPLETED', 'resync_status': 'COMPLETED', 'hash_warnings': False}, 'gunther': {'rclone_options': {}, 'bisync_options': {}, 'resync_options': {}, 'local': 'gunther', 'rclone_remote': 'gunther', 'remote': 'users/gunther', 'schedule': '0 0 * * *', 'active': True, 'dry_run': False, 'force_resync': False, 'force_operation': False, 'last_sync': '2026-02-03T12:32:23.933408', 'next_run': '2026-02-04T00:00:00', 'sync_status': 'COMPLETED', 'resync_status': 'COMPLETED', 'hash_warnings': False}}}
INFO: Daemon process started, waiting for it to initialize...# Development

Quick reference for setting up, running, and testing the app locally.

---

## Setup

**Venv and install:**

```bash
python -m venv .venv
source .venv/bin/activate   # Bash/Zsh (Linux/macOS)
# source .venv/bin/activate.fish  # Fish
# .venv\Scripts\activate          # Windows
pip install -e .
```

**With tests (pytest):**

```bash
pip install -e ".[dev]"
```

**Fish shell (full dev setup + hook):**

```fish
python -m venv .venv
source .venv/bin/activate.fish
pip install -e ".[dev]"
git config core.hooksPath githooks
```

**Tray (system deps):** GTK3, AppIndicator, libnotify — see [ARCH_AND_AUR_DEPENDENCIES.md](ARCH_AND_AUR_DEPENDENCIES.md) for Arch packages.

---

## Run

**CLI** (from repo root or after `pip install -e .`):

- `rclone-bisync-manager daemon start|stop|status|reload` — daemon
- `rclone-bisync-manager sync [job ...]` — one-off sync (`--resync`, `--force-bisync` optional)
- `rclone-bisync-manager add-sync JOB ...` — queue jobs while daemon runs
- `rclone-bisync-manager --version` — show version

**Global options:** `--config PATH`, `-d`/`--dry-run`, `--console-log`

**Tray:** `rclone-bisync-manager-tray`  
Options: `--config PATH`, `--log-level DEBUG|INFO|...`, `--icon-style 1|2`, `--icon-thickness N`, `--enable-experimental`

**Debug:** `--console-log` for daemon/sync (logs to stdout); `--log-level DEBUG` for tray.

---

## Tests

- **Run:** `pytest tests/ -v` (from repo root; needs `pip install -e ".[dev]"`).
- **Pre-commit hook:** Install once so tests run before each commit:

  ```bash
  git config core.hooksPath githooks
  ```

  Commit is aborted if tests fail. Skip once: `git commit --no-verify`.

**Python version:** Requires Python 3.12+. Optional: Python 3.14+ free-threading (PEP 703) may affect threading assumptions; not required for current usage.

---

## Tray status architecture: root cause and refactor plan

### Observed behaviour and how it fits the root cause

**Observation:** Last log line was `"INFO: Daemon process started, waiting for it to initialize..."` while the icon was still grey. When the icon finally switched to blue, the log continued with more messages (e.g. "Daemon status changed", "Status or state changed").

**Code flow that produces this:**

1. **Tray starts with daemon not running**  
   `initial_status = get_daemon_status()` → `None` → icon painted OFFLINE (grey).  
   `if initial_state == DaemonState.OFFLINE` → `Thread(target=start_daemon).start()`.

2. **start_daemon (background thread)**  
   - `get_daemon_status()` → `None` (daemon not up), so we continue.  
   - `Popen("rclone-bisync-manager daemon start")`, then `communicate(timeout=2)` or `TimeoutExpired`.  
   - Log: **"Daemon process started, waiting for it to initialize..."**  
   - **`state.update_queue.put(True)`** → schedules a UI refresh.  
   - Thread effectively finishes (no further log from start_daemon).

3. **First UI refresh after start**  
   - `handle_updates_appindicator` gets `True`, calls `GLib.idle_add(_update_appindicator_ui)`.  
   - Main thread runs `_update_appindicator_ui`, which calls **`get_daemon_status()` again**.  
   - At this moment the real daemon process may still be: forking, acquiring lock, loading config, starting the status server thread, binding the socket. So the socket may not exist yet or may not accept.  
   - **`get_daemon_status()` returns `None`** → paint with `status=None` → OFFLINE → **icon stays grey**.  
   - So the “last message” the user sees is still "waiting for it to initialize", and the icon is grey. **This matches the observation.**

4. **When the icon goes blue**  
   - `check_status_and_update` runs every 1s. Sooner or later the daemon is up; `get_daemon_status()` succeeds (status with `currently_syncing` / `queued_paths`).  
   - Inside `get_daemon_status()`: `status != state.last_status` → log **"Daemon status changed"**, update `last_status`, return status.  
   - In the poll thread: `current_status != last_status` → `state.update_queue.put(True)` → log **"Status or state changed..."** (DEBUG).  
   - Another UI refresh runs; `_update_appindicator_ui` calls `get_daemon_status()` again; this time it can succeed → SYNCING → **blue icon**.  
   - So when the icon turns blue, the log continues with "Daemon status changed" and related messages. **This also matches.**

**Conclusion:** The observed log sequence is consistent with the root cause: the icon is driven by a **second, independent** status fetch in the UI. The first refresh after “waiting for it to initialize” runs too early (daemon not ready) → that fetch returns `None` → grey. The next refresh is triggered by the poll thread’s first successful status → UI runs again, fetch can succeed → blue and more log lines.

The same pattern explains **grey while syncing**: any UI refresh that does a fresh fetch can get `None` (timeout, contention, etc.); we then paint OFFLINE even though the daemon is up and syncing.

---

### "Jobs visible but icon grey" (dropdown menu) — root cause

**User report:** The **right-click dropdown menu of the icon** showed the actual sync jobs (currently syncing, queued, Sync Jobs list) while the **icon was grey**. So communication with the daemon was working (menu had live job data), but the icon showed OFFLINE.

**Root cause (in code):** In `get_menu_spec()` we branch only on **INITIAL, FAILED, LIMBO**. Every other state (including **OFFLINE**) goes to **else** and calls **`_get_normal_spec(status)`**:

```text
if current_state == DaemonState.INITIAL:   ...
elif current_state == DaemonState.FAILED:  ...
elif current_state == DaemonState.LIMBO:   ...
else:
    spec.extend(self._get_normal_spec(status))   # ← OFFLINE goes here!
```

So when **`status` is a dict with `running` false** (so `status_to_display_state` returns **OFFLINE** → grey icon), we still build the menu with **`_get_normal_spec(status)`**, which reads **`sync_jobs`**, **`currently_syncing`**, **`queued_paths`** from that same dict and shows them in the menu. Result in a **single** run with **one** status:

- **Icon:** OFFLINE (grey), because `status.get(RUNNING, False)` is false.
- **Menu:** Built from `_get_normal_spec(status)` → shows jobs, because the dict still contains `sync_jobs`, `currently_syncing`, `queued_paths`.

So we **can** have grey icon + dropdown menu with jobs from the **same** status: the payload has **`running: false`** but still has job data.

**When does the daemon send such a payload?**

- **Shutdown:** `state.running = False`; `generate_status_report()` still builds the full payload (including `sync_jobs`, `currently_syncing`, `queued_paths` from state/store). So we send **`running: false`** with job data. The tray then paints OFFLINE (grey) and builds the menu from that payload → menu shows jobs.
- **Any edge case** where the status dict has **RUNNING false** (or missing) but the rest of the payload is still populated (e.g. race, or a response built right as the daemon is stopping).

**Fix (menu consistency):** When **`current_state == DaemonState.OFFLINE`**, do **not** use `_get_normal_spec(status)`. Use a dedicated offline menu (e.g. "Daemon is not running", "Start Daemon", same as FAILED-style) so the menu never shows jobs when the icon is grey. That makes icon and menu consistent for OFFLINE.

---

### Root cause (summary)

- **Design:** The tray uses the queue only as a **refresh trigger** (“something changed, redraw”). It does **not** pass the status that caused the change.
- **Implementation:** The UI **always** calls `get_daemon_status()` again and uses that result for icon and menu. So the painted state is from this **second** fetch, not from the poll thread’s result.
- **Effect:** Whenever that second fetch returns `None`, we show OFFLINE (grey), regardless of what the poll thread last saw (including “syncing” or “running”).

**Second issue (menu):** When we show OFFLINE (e.g. status has `running: false` but still has job data), we still build the menu with `_get_normal_spec(status)` → menu shows jobs. So grey icon + dropdown with jobs comes from a single status (see "Jobs visible but icon grey" above).

---

### Plan: robust non-blocking tray architecture (full refactor)

**Goal:** One source of truth for “what to paint”; no redundant fetch that can fail and force grey; optional reduction of duplicate work and contention.

#### 1. Single source of truth for display status

- **Option A – Paint from stored status only**  
  - The **only** place that fetches from the daemon is the poll thread (`check_status_and_update`).  
  - It writes the result into a single shared “display status” (e.g. `state.last_status` or a dedicated `state.display_status`) under a lock.  
  - The UI **never** calls `get_daemon_status()`. It only reads the stored status and paints icon/menu from it.  
  - Pros: One fetch per poll; no “second fetch fails → grey”.  
  - Cons: Poll thread must keep running and updating; need a clear rule for “when do we show OFFLINE?” (e.g. after N consecutive None, or after T seconds without update).

- **Option B – UI may fetch, but fall back to stored status**  
  - Keep current flow: UI can call `get_daemon_status()` when it runs.  
  - If that call returns `None`, **do not** paint OFFLINE; instead use the last known good status (e.g. `state.last_status`) for this paint, so we don’t show grey on a transient failure.  
  - When to show OFFLINE: only when we have **no** valid stored status (e.g. clear stored status after K consecutive None in the poll thread).  
  - Pros: Small change; still allows “fresh” data when the UI runs.  
  - Cons: Two fetches still possible; logic for “confidently offline” (clearing stored status) must be defined and tested.

**Recommendation:** Option A for a full refactor (single source of truth, clearest model). Option B as a minimal fix if refactor is deferred.

#### 2. Pass status with the refresh event (optional, supports Option A)

- Instead of “queue only carries a wake-up signal”, have the producer (poll thread) **attach the status** (or a reference) to the event when it has one.
- Examples:  
  - Queue items are `(True, status)` or a small object `{ "refresh": True, "status": status_or_None }`.  
  - Or: poll thread only updates `state.display_status` (and maybe a “dirty” flag or version); queue still carries “refresh”. UI reads `state.display_status` under lock.
- Then the UI never needs to fetch; it only applies the stored (or event-carried) status to the icon and menu.

#### 3. When to show OFFLINE (Option A)

- Define “we are offline” only when the **poll thread** has seen no successful status for a while:
  - e.g. after **N consecutive** `get_daemon_status() == None` (e.g. N ≥ 3), set `display_status = None` and treat as OFFLINE for painting.
  - Optional: time-based (e.g. “no successful status in the last T seconds”) instead of or in addition to consecutive count.
- Until then, keep painting from the last successful `display_status` (so icon stays blue/green during transient failures or right after “waiting for it to initialize”).

#### 4. Reduce duplicate work and contention (optional)

- If we move to Option A, the UI no longer calls the daemon, so duplicate status requests disappear and contention on the status socket is reduced.
- If we keep Option B, we could still **skip** the UI fetch when the refresh was triggered by the poll thread and we have a very recent stored status (e.g. “last success < 500 ms ago”) to avoid redundant requests.

#### 5. Startup behaviour (“waiting for it to initialize”) and poll-loop block

- After `start_daemon` does `put(True)`, the first UI run will paint from **stored** status. With Option A, that stored value is whatever the poll thread last wrote (e.g. still `None` at startup). So we’d show OFFLINE until the **first successful poll** after the daemon is up, then we’d show RUNNING/SYNCING. No “one fetch too early” in the UI.
- With Option B (fallback to last known): same idea—if the UI’s fetch returns `None`, we use last known; at startup that’s `None`, so we still show grey until the poll thread gets a good status and we paint from that (via fallback or stored). So startup behaviour is consistent with “single source of truth” once we have one.

**Poll-loop block (fixed):** The log line “Daemon process started, waiting for it to initialize…” was the last line until the first pending sync finished because the **poll loop** was blocking inside `get_daemon_status()` (i.e. on `request_status()` with timeout 8s × 3 attempts). While the daemon was busy with the first sync (or slow to respond), the poll thread stayed blocked, so no further log lines (e.g. “Daemon status changed”) and no UI refresh until the request returned. Fix: run the status fetch in a **worker thread** (`_status_fetch_worker`). The poll loop only starts the worker when no fetch is in progress and then sleeps; the worker does the blocking `request_status()`, then `_apply_status_result()` and `put(True)`. The log and UI can therefore progress as soon as the daemon responds, without the poll loop blocking on the socket.

#### 6. Implementation order (refactor)

1. Introduce a single **display status** (e.g. `state.display_status` + lock or use existing `state.last_status` with clear semantics).
2. **Poll thread only:**  
   - Fetch with `get_daemon_status()` (or direct `request_status`).  
   - On success: update `display_status`, reset “consecutive None” count, put refresh.  
   - On None: increment count; if count ≥ N, set `display_status = None`, put refresh; else optionally put refresh (e.g. for sync-feedback expiry) without clearing.
3. **UI only:**  
   - On refresh: read `display_status` under lock (no fetch).  
   - Compute `display_state = get_effective_state_for_display(display_status)`, paint icon and menu.  
   - Remove `get_daemon_status()` from `_update_appindicator_ui`.
4. **start_daemon / other triggers:**  
   - Keep `put(True)` to force a refresh; UI will paint from current `display_status` (may still be None until poll thread succeeds).
5. **Tests / manual:**  
   - Startup: icon goes from grey to blue/green only after first successful poll.  
   - During sync: icon stays blue/green even if a hypothetical “extra” fetch would have failed.  
   - Daemon stopped: after N consecutive None, icon goes grey.

This plan is for a **full refactor** toward Option A; Option B can be implemented first as a minimal fix (see “Direction for a real fix” in the analysis) and later replaced by Option A if desired.
