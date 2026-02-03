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
- **Global and per-job options** – Shared `rclone_options`, `bisync_options`, `resync_options`; override per job.
- **Missed jobs** – Optional run of missed jobs on daemon start; optional initial sync on startup.
- **CPU limit** – Optional cap on CPU usage for sync processes.
- **Exclusion rules** – Optional global filter file; changes trigger a resync.
- **Marker file** – Sync only runs when `RCLONE_TEST` exists in both local and remote paths (safety check).
- **System tray** – Optional tray app: status, start/stop daemon, reload config, trigger syncs, open config/logs; starts daemon if not running.
- **Status server** – Unix socket used by tray and `daemon status` for live daemon and job status.

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
yay -S rclone-bisync-manager-tray-git   # optional, for tray
```

### Other Linux (pip)

```bash
pip install rclone-bisync-manager
```

With tray support:

```bash
pip install rclone-bisync-manager[tray]
```

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
4. **Marker file** – Create `RCLONE_TEST` in both the local sync folder and the remote path (see [Setting up a sync target](#setting-up-a-sync-target)).
5. **Run** – Start the daemon: `rclone-bisync-manager daemon start`, or run the tray: `rclone-bisync-manager-tray` (it will start the daemon if needed).

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
| `exclusion_rules_file` | Optional path to filter/exclusion file. If the file changes, a resync is triggered for all jobs. |
| `max_cpu_usage_percent` | CPU limit for sync (0–100). Requires cpulimit; ignored if not installed. Default: 100. |
| `redirect_rclone_log_output` | Redirect rclone log output into the manager log file. Default: false. |
| `run_missed_jobs` | Run jobs that were missed while daemon was stopped. Default: false. |
| `run_initial_sync_on_startup` | Run an initial sync when the daemon starts. Default: true. |
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
| `force_operation` | Next run uses `--force` for bisync. |
| `rclone_options` | Job-specific rclone options (override global). |
| `bisync_options` | Job-specific bisync options. |
| `resync_options` | Job-specific resync options. |

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

### 3. Marker file (required)

- A file named **`RCLONE_TEST`** must exist in both the local sync folder and the remote path.
- If it’s missing on either side, the manager skips the sync and logs it.

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
After=network.target

[Service]
ExecStart=/usr/bin/rclone-bisync-manager daemon start
ExecStop=/usr/bin/rclone-bisync-manager daemon stop
Restart=on-failure

[Install]
WantedBy=default.target
```

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
- **Limbo** – If config becomes invalid, the daemon can enter a “limbo” state and keep running until config is fixed and reloaded.
- **Hash warnings** – Special file types (e.g. some Live Photo formats) may be reported in status; they don’t stop the sync.
- **Runtime paths** – Sockets, lock file, and crash log use the runtime base; empty env vars are ignored so the next option in the list is used.

---

## Status server

The daemon runs a status server on a Unix socket (path under the runtime base, e.g. `.../rclone_bisync_manager_status.sock`). It is used by:

- **System tray** – Live status and menu actions.
- **`rclone-bisync-manager daemon status`** – Prints current status.

Status includes: daemon PID, running/limbo/shutting down, config validity, currently syncing jobs, queued jobs, per-job last sync / next run / sync status / resync status / hash warnings, sync errors, config and log file paths.

Very large configs (many sync jobs or large job definitions) can produce a large status payload and may cause slower tray/CLI response or higher memory use; keeping job count and config size reasonable is recommended.

---

## Development

This app was developed with AI-assisted pair programming using [CLIPPY](https://github.com/Gunther-Schulz/coding-clippy) (guided AI pair programming protocol).

---

## License

MIT. See [LICENSE](LICENSE).
