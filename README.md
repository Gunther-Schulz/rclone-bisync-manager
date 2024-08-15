# RClone BiSync Manager

RClone BiSync Manager is a daemon-based solution for automated, bidirectional synchronization of files using RClone. It provides a flexible and configurable way to manage multiple sync jobs with customizable schedules and options.

**_WARNING: This is still under development and not ready for production use and may never be._**
**_WARNING: This README is neither complete not necessarily correct._**

## Features

- Daemon-based operation for continuous background syncing
- Support for multiple sync jobs with individual configurations
- Customizable sync schedules using cron syntax
- Global and per-job RClone options
- System tray application for easy status monitoring and control
- Dry-run mode for testing configurations
- CPU usage limiting to prevent system overload
- Configurable exclusion rules
- Automatic handling of missed sync jobs

## Requirements

- Python 3.12 or higher
- RClone installed and configured on your system

## Installation

You can install RClone BiSync Manager using pip:

```
pip install rclone-bisync-manager
```

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

Adjust the configuration to match your specific sync requirements.

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

### Running a Manual Sync

To run a manual sync for specific jobs:

```
rclone-bisync-manager sync [job1] [job2] ...
```

If no job names are specified, all active jobs will be synced.

### System Tray Application

To start the system tray application:

```
rclone-bisync-manager-tray
```

This provides a convenient way to monitor sync status and control the daemon.

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

RClone BiSync Manager can be run as a user service, which is recommended for most users. This allows the service to run under your user account without requiring root privileges.

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

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
