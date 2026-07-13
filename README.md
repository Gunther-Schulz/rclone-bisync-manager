![RClone BiSync Manager](desktop/rclone-bisync-manager.svg)

# RClone BiSync Manager

A daemon-based manager for automated, bidirectional file sync using [rclone bisync](https://rclone.org/commands/rclone_bisync/). Configure multiple jobs with cron schedules, global and per-job rclone options, and optional system-tray control.

**Note:** Beta — suitable for production use with backups; please report bugs. See [Disclaimer](#rclone-bisync-manager) below.

**Disclaimer:** Use at your own risk. Data loss is possible with any sync application—misconfiguration, bugs, or conflicts can affect your files. The risk is reduced because the actual sync is performed by [rclone](https://rclone.org/), which is mature and widely used; this app only schedules and invokes rclone. Still, keep backups of important data and test with non-critical paths first.

**Version:** The app version is defined in `pyproject.toml` (single source of truth). Check it with `rclone-bisync-manager --version` or `pip show rclone-bisync-manager`. GitHub releases are tagged (e.g. `v0.1.0`).

---

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Setting up rclone (fresh system)](#setting-up-rclone-fresh-system)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Setting up a sync target](#setting-up-a-sync-target)
- [Usage (CLI)](#usage-cli)
- [System tray](#system-tray)
- [Paths and environment](#paths-and-environment)
- [Desktop integration](#desktop-integration)
- [Systemd service](#systemd-service)
- [Error handling and logging](#error-handling-and-logging)
- [Status server](#status-server)
- [Development](#development)
- [License](#license)

---

## Features

- **Daemon** – Runs in the background; schedules and runs sync jobs with cron-style timing.
- **Multiple jobs** – Each job has its own local path, remote, schedule, and optional overrides.
- **Cron schedules** – Use standard cron expressions (e.g. `*/30 * * * *` for every 30 minutes).
- **Global and per-job options** – Shared `rclone_options`, `bisync_options`, `resync_options`; override per job (most specific wins).
- **Missed jobs** – Optional run of missed jobs on daemon start; optional initial sync on startup.
- **CPU limit** – Optional cap on CPU usage for sync processes.
- **Filter rules** – Optional filter file (rclone `--filters-file` format). Any change to your filtering — the file *or* the `exclude`/`include` options — forces a resync of the affected jobs first, so newly-excluded files are never mistaken for deletions.
- **Access check** – Opt-in: set `check_access` and sync only runs when the `RCLONE_TEST` marker exists on both sides.
- **System tray** – Optional tray app: status, start/stop daemon, reload config, trigger syncs, open config/logs; starts daemon if not running.
- **Status server** – Unix socket used by tray and `daemon status` for live daemon and job status.

---

## Upgrading — behavior changes

If you ran an earlier version, four things changed on purpose:

- **Your filter file must be rewritten as an rclone filters file.** It is now passed as
  `--filters-file` instead of `--exclude-from`, so every rule needs a `-` (exclude) or `+`
  (include) prefix. The daemon refuses to start otherwise and tells you which lines to fix.

  ```diff
  - *.tmp          # old: bare pattern (--exclude-from)
  + - *.tmp        # new: an exclude rule (--filters-file)
  ```

  This buys a real guard: rclone hashes the filters file and **aborts** rather than sync if it
  changed without a resync. Under `--exclude-from` it tracked nothing, so editing your filters
  silently deleted the newly-excluded files on the other side. (rclone writes a `.md5` file next
  to your filters file — that's expected.)

- **The `RCLONE_TEST` marker file is no longer required by default.** It is now opt-in via
  `check_access` (matching rclone's own default). If you relied on the marker as a guard against
  syncing an unmounted drive, **add `check_access: null` to `rclone_options`** to keep it; your
  existing marker files are still valid. Deletions remain guarded by `max_delete` either way.
- **Adding a job no longer starts syncing it immediately.** A never-synced job is scheduled at its
  next cron time instead of being treated as a "missed" run. To start a new job's first (full,
  expensive) resync on purpose, set `run_initial_sync_on_startup: true`, or run
  `rclone-bisync-manager sync <job>`.
- **`dry_run` now actually works.** It was silently ignored — both globally and per job. If you
  have `dry_run: true` sitting in a config somewhere, that job will now genuinely dry-run rather
  than sync for real.

---

## Requirements

- **Python** 3.12 or higher  
- **rclone** – Installed and configured (remotes set up via `rclone config`)  
- **Tray (optional)** – For the system tray app: GTK3, AppIndicator/libappindicator, libnotify (see [ARCH_AND_AUR_DEPENDENCIES.md](ARCH_AND_AUR_DEPENDENCIES.md) for Arch packages).

---

## Installation

### Arch Linux (AUR)

```bash
yay -S rclone-bisync-manager-git
```

### Other Linux (pip)

```bash
pip install rclone-bisync-manager
```

The package includes the daemon, CLI, and system tray.

---

## Setting up rclone (fresh system)

The manager runs **rclone** for you; you only need rclone installed and at least one **remote** configured. This section is a short checklist for a fresh system. For backend-specific setup (OAuth, tokens, etc.), see the [rclone documentation](https://rclone.org/docs/).

### 1. Install rclone

- **Linux:** Use your distro package (e.g. `pacman -S rclone`, `apt install rclone`) or the [official install script](https://rclone.org/install/).
- **Verify:** `rclone version`

### 2. Create a remote

- Run: `rclone config`
- Choose **n** (new remote), give it a **name** (e.g. `gdrive`, `mydrive`). This name is what you put in `rclone_remote` in the manager config.
- Choose the **backend** (Google Drive, S3, SFTP, local, etc.) and follow the prompts (OAuth, keys, paths — see [rclone backends](https://rclone.org/overview/) for your provider).
- When done, **q** to quit.

### 3. Where rclone stores config

- **Default:** `~/.config/rclone/rclone.conf` (or `$XDG_CONFIG_HOME/rclone/rclone.conf` if set).
- The manager runs rclone as the same user, so it uses this file automatically. You can override with the `RCLONE_CONFIG` environment variable if needed.

### 4. Verify the remote

```bash
rclone listremotes
```

You should see your remote name. Optionally list the root (or the path you will use) to confirm it’s writable:

```bash
rclone lsd myremote:
rclone lsd myremote:path/to/folder
```

### 5. Optional: security and env vars

- **Encrypted config:** rclone supports [config encryption](https://rclone.org/docs/#config-file); set a password when prompted in `rclone config` or use `RCLONE_CONFIG_PASS` for headless use.
- **Secrets in env:** Some backends allow passing credentials via environment variables instead of the config file; see the backend’s docs on [rclone.org](https://rclone.org/).

Once at least one remote exists, continue with [Quick start](#quick-start) and [Setting up a sync target](#setting-up-a-sync-target).

---

## Quick start

1. **Config file** – Create `~/.config/rclone-bisync-manager/config.yaml` (or set `XDG_CONFIG_HOME` / use `--config PATH`).
2. **Minimal config** – Set `local_base_path`, define at least one job in `sync_jobs` with `local`, `rclone_remote`, `remote`, and `schedule`. See [Configuration](#configuration) and `examples/config.yaml.example`.
3. **Rclone remote** – Ensure the remote exists (`rclone listremotes`) and the remote path is writable.
4. **Run** – Start the daemon: `rclone-bisync-manager daemon start`, or run the tray: `rclone-bisync-manager-tray` (it will start the daemon if needed).

That's all you need. Deletions are guarded out of the box by bisync's `--max-delete` (50% by default). If you want the stricter marker-file check on top, see [Setting up a sync target](#setting-up-a-sync-target).

---

## Configuration

### Config file location

- **Default:** `$XDG_CONFIG_HOME/rclone-bisync-manager/config.yaml` (if `XDG_CONFIG_HOME` is unset, `~/.config/...` is used).
- **Override:** `--config PATH` for any CLI or tray command.
- Empty or unset `XDG_CONFIG_HOME` is treated as “use default”; see [Paths and environment](#paths-and-environment).

### Structure overview

| Section | Purpose |
|--------|---------|
| **Global** | `local_base_path`, `exclusion_rules_file`, `max_cpu_usage_percent`, `redirect_rclone_log_output`, `run_missed_jobs`, `run_initial_sync_on_startup`, `dry_run`, `log_file_path`, `log_rotation_max_mb`, `log_rotation_backup_count` |
| **sync_jobs** | One entry per job: `local`, `rclone_remote`, `remote`, `schedule`, `active`, `dry_run`, `force_resync`, `force_operation`, `rclone_options`, `bisync_options`, `resync_options` |
| **rclone_options** | Applied to all jobs; can be overridden per job |
| **bisync_options** | Bisync-specific; can be overridden per job |
| **resync_options** | Resync-specific; can be overridden per job |

### Global options

| Option | Description |
|--------|-------------|
| `local_base_path` | Base directory for all local sync paths (required). |
| `exclusion_rules_file` | Optional path to an rclone **filters file**. Every rule must start with `-` (exclude) or `+` (include) — e.g. `- *.tmp`. Passed to rclone as `--filters-file`. If it changes, the affected jobs resync before syncing again. |
| `max_cpu_usage_percent` | CPU limit for sync (0–100). Requires cpulimit; ignored if not installed. 100 means no limit (cpulimit is not used at all). Default: 100. |
| `redirect_rclone_log_output` | Write rclone's output to `rclone.log`, next to the daemon log. It is deliberately a separate file: rclone holds its log open for the whole run, so sharing the daemon's rotating log meant rotation renamed the file out from under it. Rotated at 50 MB between runs. Default: false. |
| `run_missed_jobs` | On daemon start, run jobs whose scheduled time passed while the daemon was stopped. A job that has never synced has not "missed" anything and is not included — it is simply scheduled at its next cron time. Default: false. |
| `run_initial_sync_on_startup` | Sync every active job once when the daemon starts. This is how you deliberately kick off a new job's first (full, expensive) resync. Default: false. |
| `dry_run` | Global dry run (no actual changes). Default: false. |
| `log_file_path` | Daemon log file path. Default: under `$XDG_STATE_HOME/rclone-bisync-manager/logs/` (e.g. `~/.local/state/...` if unset). |
| `log_rotation_max_mb` | Max log size in MB before rotation. Omit or leave empty for default (5). |
| `log_rotation_backup_count` | Number of rotated log files to keep. Omit or empty for default (5). |

### sync_jobs

Each job is a key (e.g. `documents`) with:

| Field | Description |
|-------|-------------|
| `local` | Local path relative to `local_base_path`. |
| `rclone_remote` | Name of the rclone remote. |
| `remote` | Path on the remote. |
| `schedule` | Cron expression (e.g. `0 * * * *` = hourly). |
| `active` | If true, job is scheduled. Default: true. |
| `dry_run` | Job-level dry run. Default: false. |
| `force_resync` | Next run does a full resync before bisync. |
| `force_operation` | Every run of this job passes `--force` to bisync, which **disables rclone's `--max-delete` safety check** — deletions become unlimited. This is persistent: it stays in effect until you remove it from the config. It does **not** repair a job that needs a resync; use `force_resync` for that. |
| `rclone_options` | Job-specific rclone options (override global). |
| `bisync_options` | Job-specific bisync options. |
| `resync_options` | Job-specific resync options. |

**Option precedence** — most specific wins:

```
rclone_options (global)  <  bisync_options/resync_options (global)
                         <  rclone_options (job)
                         <  bisync_options/resync_options (job)
```

---

## Safety: what stops a bad sync from deleting your files

Bisync propagates deletions in *both* directions, so it is worth knowing exactly what guards you.

| Guard | Default | What it does |
|-------|---------|--------------|
| `max_delete` | **50** (rclone's default) | **A PERCENTAGE, not a file count.** If more than this share of files on either side would be deleted, rclone aborts the run without changing anything. This is what saves you when a drive fails to mount and a folder suddenly looks empty. Setting `max_delete: 5` means 5%, not 5 files. |
| `check_access` | off | Requires an `RCLONE_TEST` marker on both sides before syncing. A second, stricter layer — see [Setting up a sync target](#setting-up-a-sync-target). |
| Filter-change resync | always on | Changing what you filter (the filters file, or any `exclude`/`include`/`min-size`/`max-age` option) makes previously-synced files drop out of rclone's listings — which bisync would read as deletions and propagate. Affected jobs are forced to resync first. |
| `force_operation` / `--force-bisync` | off | **Turns `max_delete` OFF.** Deletions become unlimited. Only use it when you have decided that a large deletion is correct. |

If a job needs repairing, `force_resync` is almost always the thing you want — **not** `--force`.

### rclone_options / bisync_options / resync_options

- **Global** – Apply to all jobs unless overridden.
- **Per job** – Merge with or override global options.
- **Disallowed keys** (reserved by the manager): `resync`, `bisync`, `log-file`. Do not put these in option dicts.
- Use `null` for flags that take no value (e.g. `recover: null`). See [rclone documentation](https://rclone.org/flags/).

Example (see `examples/config.yaml.example` for a full file):

```yaml
local_base_path: /mnt/data
sync_jobs:
  docs:
    local: Documents
    rclone_remote: gdrive
    remote: backup/documents
    schedule: "0 * * * *"
rclone_options:
  log_level: INFO
  exclude: ["*.tmp", "*.log"]
bisync_options:
  conflict_resolve: newer
  conflict_loser: num
```

---

## Setting up a sync target

Before a job can run, the following must be in place.

### 1. Rclone remote

- The job’s `rclone_remote` must match a remote from `rclone listremotes`.
- If you don’t have a remote yet, see [Setting up rclone (fresh system)](#setting-up-rclone-fresh-system).

### 2. Local folder

- Full local path = **`local_base_path`** + **`local`**.
- Example: `local_base_path: /mnt/data` and `local: MySync` → create `/mnt/data/MySync`.

### 3. Marker file (optional, opt-in)

**You can skip this.** Nothing here is needed for a normal setup — bisync already refuses to
run if more than `--max-delete` percent of files would be deleted (50% by default), which is
what protects you if a drive fails to mount or a folder is wiped.

The marker file is a second, stricter layer: rclone's `--check-access` refuses to sync unless
a matching **`RCLONE_TEST`** file is found on *both* sides. It's worth enabling when the local
path is a removable or network mount that could silently appear empty. It is **off by default**,
matching rclone's own default.

To enable it, add `check_access` to `rclone_options` in your config:

```yaml
rclone_options:
  check_access: null # null means "pass the bare --check-access flag"
```

Then create the marker on both sides, or every sync for that job will fail (with a message
telling you exactly this).

**Local:**

```bash
touch /mnt/data/MySync/RCLONE_TEST
```

**Remote** (replace `myremote` and path with your `rclone_remote` and `remote`):

```bash
rclone touch "myremote:backup/MySync/RCLONE_TEST"
```

If the backend doesn’t support empty files:

```bash
echo -n "" | rclone rcat "myremote:backup/MySync/RCLONE_TEST"
```

To use a different filename, set `check_filename` alongside `check_access`; the manager will
look for that name instead.

### 4. Remote path writable

- Some backends (e.g. HiDrive) don’t allow writing at root. Use a writable subpath (e.g. `users/yourusername/MySync`).

### 5. Optional: exclusion rules file

- If `exclusion_rules_file` is set, the path must exist (create an empty file if you have no rules yet).

### 6. Test with dry run

```bash
rclone-bisync-manager sync myjob --config /path/to/config.yaml -d
rclone-bisync-manager sync myjob --config /path/to/config.yaml
```

---

## Usage (CLI)

All commands accept optional **`--config PATH`** to use a config file other than the default.

### Global options (CLI)

- **`--version`** / **`-V`** – Print version and exit (no config loaded).
- **`--config PATH`** – Config file path.
- **`-d` / `--dry-run`** – Dry run (no changes).
- **`--console-log`** – Also print log messages to the console (useful for daemon start debugging).

### Daemon

```bash
rclone-bisync-manager daemon start    # Start daemon (never returns on success)
rclone-bisync-manager daemon stop     # Stop daemon via socket
rclone-bisync-manager daemon status   # Print status from status server
rclone-bisync-manager daemon reload   # Reload config without restart
```

### Sync (one-off)

```bash
rclone-bisync-manager sync [job1 [job2 ...]]
```

- If no jobs are given, all active jobs are synced.
- **`--resync JOB_KEY [JOB_KEY ...]`** – Force a full resync for the given job(s) before bisync.
- **`--force-bisync`** – Use `--force` for the bisync step.

Examples:

```bash
rclone-bisync-manager sync
rclone-bisync-manager sync docs -d
rclone-bisync-manager sync docs --resync docs --force-bisync
```

### Add sync (queue jobs while daemon is running)

```bash
rclone-bisync-manager add-sync job1 [job2 ...]
```

- Sends the listed jobs to the daemon’s queue for immediate execution (same as triggering from the tray).

---

## System tray

The tray app shows daemon and job status and lets you start/stop the daemon, reload config, trigger syncs, and open config/logs.

### Running the tray

```bash
rclone-bisync-manager-tray [options]
```

- If the daemon is not running, the tray will start it (using the same config path if you pass `--config`).

### Tray options

| Option | Description |
|--------|-------------|
| `--config PATH` | Config file (default: same XDG/default as CLI). |
| `--icon-style 1\|2` | Icon style. Default: 1. |
| `--icon-thickness N` | Line thickness for icon. Default: 40. |
| `--log-level NONE\|DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL` | Tray logging level. Default: NONE. |
| `--enable-experimental` | Enable experimental features. |

### Icon colors

- **Green** – Daemon running, no issues.
- **Blue** – Sync in progress.
- **Yellow** – Initializing or config changed.
- **Red** – Sync issues or errors.
- **Gray** – Daemon offline.

### Menu

- Start/stop daemon, reload config, trigger sync (normal or force/resync), open or edit config file (GTK editor), open log folder, open status window, quit.

---

## Paths and environment

Paths follow the [XDG Base Directory](https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html) convention where applicable. Empty or unset env vars are treated as “use default” (no relative paths).

| Purpose | Default | Override |
|---------|---------|----------|
| **Config file** | `$XDG_CONFIG_HOME/rclone-bisync-manager/config.yaml` (e.g. `~/.config/...`) | `--config PATH` or set `XDG_CONFIG_HOME` |
| **Daemon log** | `$XDG_STATE_HOME/rclone-bisync-manager/logs/rclone-bisync-manager.log` (e.g. `~/.local/state/...`) | `log_file_path` in config |
| **Cache** (state, errors, status files) | `$XDG_CACHE_HOME/rclone-bisync-manager` (e.g. `~/.cache/...`) | Set `XDG_CACHE_HOME` |
| **Runtime** (sockets, lock, crash log) | First of: `RCLONE_BISYNC_MANAGER_RUNTIME_DIR`, `XDG_RUNTIME_DIR`, `/tmp` | Set env vars above |

---

## Desktop integration

- **Desktop file:** `desktop/rclone-bisync-manager-tray.desktop`
- Install: copy to `~/.local/share/applications/` or `/usr/share/applications/`, make executable if needed.
- **Icon:** `desktop/rclone-bisync-manager.svg` – install to e.g. `~/.local/share/icons/hicolor/scalable/apps/` or `/usr/share/icons/hicolor/scalable/apps/` as `rclone-bisync-manager.svg` (name must match the desktop file `Icon=`).

---

## Systemd service

Run the daemon as a **user** service (recommended; no root).

1. Create `~/.config/systemd/user/rclone-bisync-manager.service`:

```ini
[Unit]
Description=RClone BiSync Manager Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/rclone-bisync-manager daemon start
ExecStop=/usr/bin/rclone-bisync-manager daemon stop
ExecReload=/usr/bin/rclone-bisync-manager daemon reload
Restart=on-failure

# Signal only the daemon, not the whole cgroup — otherwise systemd SIGTERMs rclone directly and
# aborts a bisync mid-transfer.
KillMode=mixed
KillSignal=SIGTERM

# A first resync of a large remote can run for hours; let it finish instead of being killed.
TimeoutStopSec=2h

[Install]
WantedBy=default.target
```

> The `Type=simple` / `KillMode=mixed` combination matters. The daemon detects that systemd
> started it and does not daemonize; without `Type=simple` the older unit double-forked, systemd
> saw the process it tracked exit 0, declared the service dead, and killed the real daemon —
> and because the exit looked clean, `Restart=on-failure` did not bring it back. A copy of this
> unit ships in `systemd/rclone-bisync-manager.service`.

2. Enable and start:

```bash
systemctl --user enable rclone-bisync-manager.service
systemctl --user start rclone-bisync-manager.service
```

3. Status and logs:

```bash
systemctl --user status rclone-bisync-manager.service
journalctl --user -u rclone-bisync-manager.service
```

- Adjust `ExecStart`/`ExecStop` if the binary is not in `/usr/bin` (e.g. after `pip install --user`, use the path from `which rclone-bisync-manager`).
- For a **system-wide** service, use `/etc/systemd/system/` and `systemctl` (without `--user`); usually not needed.

---

## Error handling and logging

- **Daemon log** – Location from config (`log_file_path`) or status/tray; supports rotation (`log_rotation_max_mb`, `log_rotation_backup_count`).
- **Crash log** – Written on daemon crash; path is under the runtime base (see [Paths and environment](#paths-and-environment)), e.g. `.../rclone_bisync_manager_crash.log`.
- **Limbo** – If the config becomes invalid while the daemon is running, a failed `daemon reload` puts it into a “limbo” state: it keeps running (with the last good config) until the config is fixed and reloaded. `daemon status` and `daemon stop` keep working even when the config on disk is invalid. (A config that is already invalid at `daemon start` is a hard failure — the daemon does not start.)
- **Hash warnings** – Special file types (e.g. some Live Photo formats) may be reported in status; they don’t stop the sync.
- **Runtime paths** – Sockets, lock file, and crash log use the runtime base; empty env vars are ignored so the next option in the list is used.

---

## Status server

The daemon runs a status server on a Unix socket (path under the runtime base, e.g. `.../rclone_bisync_manager_status.sock`). It is used by:

- **System tray** – Live status and menu actions.
- **`rclone-bisync-manager daemon status`** – Prints current status.

Status includes: daemon PID, running/limbo/shutting down, config validity, currently syncing jobs, queued jobs, per-job last sync / next run / sync status / resync status / hash warnings, sync errors, config and log file paths.

---

## Development

This app was developed with AI-assisted pair programming using [CLIPPY](https://github.com/Gunther-Schulz/coding-clippy) (guided AI pair programming protocol).

---

## License

MIT. See [LICENSE](LICENSE).
