![RClone BiSync Manager](desktop/rclone-bisync-manager.svg)

# RClone BiSync Manager

RClone BiSync Manager is a daemon-based solution for automated, bidirectional synchronization of files using RClone. It provides a flexible and configurable way to manage multiple sync jobs with customizable schedules and options.

**_WARNING: This is still under development and not ready for production use._**

## Notes

In Gnome, for the tray to work, you need to have the following extension installed: `AppIndicator and KStatusNotifierItem Support`

## Features

RClone BiSync Manager offers a comprehensive set of features, including:

- Daemon-based operation for continuous background syncing
- Support for multiple sync jobs with individual configurations
- Customizable sync schedules using cron syntax
- Global and per-job RClone options
- Automatic handling of missed sync jobs
- System tray application for easy status monitoring and control, featuring:
  - Real-time status monitoring of the daemon and sync jobs
  - Quick access to start/stop the daemon
  - Easy configuration reloading
  - Ability to trigger manual syncs
  - Access to configuration and log files
  - Visual indicators for sync status and issues

To start the system tray application:

```
rclone-bisync-manager-tray [options]
```

Options:

- `--icon-style <1|2>`: Choose between two different icon styles (default: 1)
- `--icon-thickness <value>`: Set the thickness of the icon lines (default: 40)
- `--log-level <NONE|DEBUG|INFO|WARNING|ERROR|CRITICAL>`: Set the logging level (default: NONE)
- `--enable-experimental`: Enable experimental features

The tray application will start the daemon if it is not already running.

The system tray icon changes color and shape to indicate the current status of the sync jobs:

- Green: Daemon running normally
- Blue: Sync in progress
- Yellow: Initializing or configuration changed
- Red: Sync issues or errors
- Gray: Daemon offline

Clicking the tray icon provides a menu with options to control the daemon, view status, and access configuration settings.

## Installation

### Arch Linux

For Arch Linux, you can install the package from the AUR:

```
yay -S rclone-bisync-manager-git
yay -S rclone-bisync-manager-tray-git
```

### Other Linux

You can install RClone BiSync Manager using pip:

```
pip install rclone-bisync-manager
```

To install with system tray support, use:

```
pip install rclone-bisync-manager[tray]
```

### Requirements

- Python 3.12 or higher
- RClone installed and configured on your system

## Configuration

1. Create a configuration file at `~/.config/rclone-bisync-manager/config.yaml`
2. Use the example configuration file as a template:

```yaml
local_base_path: /path/to/your/local/base/directory
exclusion_rules_file: /path/to/your/filter.txt
redirect_rclone_log_output: true
max_cpu_usage_percent: 100
run_missed_jobs: true
run_initial_sync_on_startup: true

sync_jobs:
  example_job:
    local: example_folder
    rclone_remote: your_remote
    remote: path/on/remote/storage
    schedule: "*/30 * * * *"
    dry_run: false
    rclone_options:
      log_level: Notice

rclone_options:
  recover: null
  resilient: null
  max_delete: 5
  log_level: INFO
  max_lock: 15m
  retries: 3
  low_level_retries: 10
  compare: "size,modtime,checksum"
  create_empty_src_dirs: null
  check_access: null
  exclude:
    - "*.tmp"
    - "*.log"

bisync_options:
  conflict_resolve: newer
  conflict_loser: num
  conflict_suffix: rc-conflict
  track_renames: null

resync_options:
  error_on_no_transfer: null
```

Adjust the configuration to match your specific sync requirements. Here's an explanation of the different option sections:

### Global Options

These options apply to the overall behavior of RClone BiSync Manager:

- `local_base_path`: The base directory for all local sync paths.
- `exclusion_rules_file`: Optional: Path to a file containing exclusion rules for syncing.
- `redirect_rclone_log_output`: Whether to redirect rclone's log output to the manager's log file.
- `run_missed_jobs`: Whether to run missed jobs when the daemon starts.
- `run_initial_sync_on_startup`: Whether to perform an initial sync when the daemon starts.
- `max_cpu_usage_percent`: Maximum CPU usage allowed for sync operations.

### sync_jobs

This section defines individual sync jobs. Each job is identified by a unique key and has the following options:

- `local`: The local directory path (relative to `local_base_path`) for this sync job.
- `rclone_remote`: The name of the rclone remote to use.
- `remote`: The path on the remote storage for this sync job.
- `schedule`: A cron-style schedule for when this job should run.
- `dry_run`: Whether to perform a dry run (no actual changes) for this job. Default: false.
- `active`: Whether this job is active and should be run by the daemon. Default: true.
- `rclone_options`: Job-specific rclone options that override general options (see below).
- `bisync_options`: Job-specific bisync options that override general options (see below).
- `resync_options`: Job-specific resync options that override general options (see below).

Example sync job configuration:

```yaml
sync_jobs:
  documents:
    local: Documents
    rclone_remote: gdrive
    remote: backup/documents
    schedule: "0 * * * *"
    dry_run: false
    rclone_options:
      log_level: INFO
```

This configuration will sync the local "Documents" folder with the "backup/documents" folder on the "gdrive" remote every hour.

### rclone_options

These are general rclone options that apply to all operations. Some common options include:

- `recover`, `resilient`: Set to `null` to enable these flags without a value.
- `max_delete`: Maximum number of files to delete during sync.
- `log_level`: Logging verbosity (DEBUG, INFO, NOTICE, ERROR).
- `max_lock`: Maximum time to hold locks.
- `retries`, `low_level_retries`: Number of retry attempts for failed operations.
- `compare`: Criteria for file comparison.
- `create_empty_src_dirs`, `check_access`: Set to `null` to enable these flags.
- `exclude`: List of patterns to exclude from sync.

### bisync_options

These options are specific to the bisync operation:

- `conflict_resolve`: How to resolve conflicts (e.g., "newer", "older", "larger", "smaller").
- `conflict_loser`: What to do with the loser of a conflict (e.g., "delete", "num", "left", "right").
- `conflict_suffix`: Suffix to add to conflict loser files.
- `track_renames`: Set to `null` to enable rename tracking.

### resync_options

These options are used during the resync operation:

- `error_on_no_transfer`: Set to `null` to make resync fail if no files were transferred.

Note: When an option is set to `null`, it means the flag will be passed to rclone without a value. This is useful for boolean flags that don't require a value but need to be present to be activated.

You can find a complete list of available options in the [rclone documentation](https://rclone.org/flags/).

## Usage

### Starting the Daemon

To start the RClone BiSync Manager daemon:

```
rclone-bisync-manager daemon start
```

### Stopping the Daemon

To stop the daemon:

```
rclone-bisync-manager daemon stop
```

### Checking Daemon Status

To check the status of the daemon:

```
rclone-bisync-manager daemon status
```

### Reloading Configuration

To reload the daemon configuration without restarting:

```
rclone-bisync-manager daemon reload
```

### Running a Manual Sync

To run a manual sync for specific jobs:

```
rclone-bisync-manager sync [job1] [job2] ...
```

If no job names are specified, all active jobs will be synced.

### Adding Sync Jobs

To add sync jobs to the queue while the daemon is running:

```
rclone-bisync-manager add-sync [job1] [job2] ...
```

This command allows you to manually trigger sync jobs without stopping the daemon.

## Desktop Integration

A desktop file is provided for easy integration with desktop environments. To install it:

1. Copy the `rclone-bisync-manager-tray.desktop` file to `/usr/share/applications/` (system-wide) or `~/.local/share/applications/` (single user).
2. Make the file executable:
   ```
   chmod +x /path/to/rclone-bisync-manager-tray.desktop
   ```
3. Ensure you have an icon file named `rclone-bisync-manager.png` or `rclone-bisync-manager.svg` in an appropriate icon directory (e.g., `/usr/share/icons/hicolor/scalable/apps/` for SVG).

After installation, you should be able to find and launch the RClone BiSync Manager Tray application from your desktop environment's application menu.

## Systemd Service

RClone BiSync Manager can be run as a user service, which is recommended if you decide not to use the tray application although both can be used at the same time. This allows the service to run under your user account without requiring root privileges.

To set up RClone BiSync Manager as a user service:

1. Create a directory for user services if it doesn't exist:

   ```
   mkdir -p ~/.config/systemd/user/
   ```

2. Create a file named `rclone-bisync-manager.service` in `~/.config/systemd/user/` with the following content:

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

3. Enable and start the service:

   ```
   systemctl --user enable rclone-bisync-manager.service
   systemctl --user start rclone-bisync-manager.service
   ```

4. To check the status of the service:

   ```
   systemctl --user status rclone-bisync-manager.service
   ```

5. To view the logs:

   ```
   journalctl --user -u rclone-bisync-manager.service
   ```

By running RClone BiSync Manager as a user service, it will start automatically when you log in and run with your user permissions.

### Running as a System Service (Alternative)

If you prefer to run RClone BiSync Manager as a system-wide service, you can create the service file in `/etc/systemd/system/` instead and use `sudo` with the systemctl commands. However, this is generally not recommended unless you have a specific reason to run it system-wide.

## Error Handling and Logging

RClone BiSync Manager provides comprehensive error handling and logging:

- Sync errors are logged and can be viewed in the status report.
- A crash log is maintained at `/tmp/rclone_bisync_manager_crash.log`.
- The daemon enters a "limbo" state if the configuration becomes invalid, allowing for recovery without stopping the service.
- Hash warnings for special file types (e.g., Live Photos) are detected and reported.

You can view the full log file location in the status report or system tray application.

## Status Server

RClone BiSync Manager runs a status server that provides real-time information about the daemon and sync jobs. This server is used by the system tray application and the `daemon status` command to retrieve current status information.

The status report includes:

- Daemon process information
- Configuration status
- Currently syncing jobs
- Queued sync jobs
- Sync job details (last sync time, next scheduled run, sync status)
- Error information

You can access this information programmatically by connecting to the Unix socket at `/tmp/rclone_bisync_manager_status.sock`.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
