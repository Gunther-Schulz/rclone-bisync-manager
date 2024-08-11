# RClone BiSync Manager

RClone BiSync Manager is a daemon-based solution for automated, bidirectional synchronization of files between local directories and remote storage supported by RClone. This Python script runs in the background, providing continuous synchronization with features such as periodic syncing, detailed logging, and real-time status reporting.

## TODO

- Check if all config changes are reloaded on the fly
- Check command line options if they still work

## Key Features

- **Daemon-based Operation**: Runs continuously in the background, managing synchronization tasks without user intervention.
- **Periodic Synchronization**: Automatically syncs files at user-defined intervals for each sync path.
- **Real-time Status Reporting**: Provides up-to-date information on sync operations and daemon status.
- **Dynamic Configuration Reloading**: Automatically detects and applies configuration changes without restarting the daemon.
- **Graceful Shutdown Handling**: Ensures clean termination of sync operations when stopping the daemon.

Additional features include:

- Bidirectional Synchronization between local and remote directories
- Dry Run Option for testing without making actual changes
- Detailed Logging with separate error logs
- CPU Usage Limiting during sync operations (requires cpulimit)
- Flexible RClone Options for customizing sync behavior

## Opinionated Settings

To ensure robust operation, RClone BiSync Manager always uses the following RClone settings:

- `--recover`: Attempts to recover from a failed sync.
- `--resilient`: Continues the sync even if some files can't be transferred.

## Prerequisites

- `rclone` (required)
- `mkdir`, `grep`, `awk`, `find`, `md5sum` (required)
- `cpulimit` (optional, for CPU usage limiting)
- Python 3.6+
- Required Python packages (install via `pip install -r requirements.txt`):
  - pyyaml
  - python-daemon

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/yourusername/rclone-bisync-manager.git
   cd rclone-bisync-manager
   ```

2. Install required Python packages:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy the example configuration:

   ```bash
   mkdir -p ~/.config/rclone_bisync_manager
   cp config/config.yaml.example ~/.config/rclone_bisync_manager/config.yaml
   ```

4. Edit the configuration file to suit your needs:

   ```bash
   nano ~/.config/rclone_bisync_manager/config.yaml
   ```

## Usage

RClone BiSync Manager can operate in two modes: daemon mode and sync mode.

### Global Options

These options can be used with any command:

- **-d, --dry-run**: Perform a dry run without making actual changes.
- **--console-log**: Enable logging to the console in addition to log files.

### Daemon Mode

To manage the RClone BiSync Manager daemon:

```bash
./rclone_bisync_manager.py daemon [start|stop|status]
```

Examples:

- Start the daemon: `./rclone_bisync_manager.py daemon start`
- Stop the daemon: `./rclone_bisync_manager.py daemon stop`
- Get daemon status: `./rclone_bisync_manager.py daemon status`
- Start daemon in dry-run mode: `./rclone_bisync_manager.py -d daemon start`

### Sync Mode

In sync mode, the script performs a single sync operation and then exits:

```bash
./rclone_bisync_manager.py sync [folders] [options]
```

Options:

- **folders**: Specify particular folders to sync (optional, syncs all if not specified).
- **--resync**: Force a resynchronization of specified folders.
- **--force-bisync**: Force a bisync operation.

Examples:

- Sync all folders: `./rclone_bisync_manager.py sync`
- Sync specific folders: `./rclone_bisync_manager.py sync folder1 folder2`
- Force resync of a folder: `./rclone_bisync_manager.py sync folder1 --resync`
- Dry run for all folders: `./rclone_bisync_manager.py -d sync`
- Force bisync with console logging: `./rclone_bisync_manager.py sync folder1 --force-bisync --console-log`

## Configuration

The configuration file (`~/.config/rclone_bisync_manager/config.yaml`) contains all necessary settings for the synchronization process. Key configuration options include:

- `local_base_path`: Base path for local files to be synced
- `exclusion_rules_file`: File containing rules for excluding files/directories from sync
- `max_cpu_usage_percent`: CPU usage limit as a percentage
- `sync_paths`: Define the paths to be synchronized
- `rclone_options`: Customize rclone options
- `bisync_options`: Customize bisync-specific options
- `resync_options`: Customize resync-specific options

Refer to the comments in the example configuration file for detailed explanations of each option.

## Logs

Logs are stored in the default log directory:

```
~/.local/state/rclone-bisync-manager/logs/
```

This directory contains two main log files:

- `rclone-bisync-manager.log`: Contains detailed information about sync operations.
- `rclone-bisync-manager-error.log`: Contains error messages and warnings.

## Automating Synchronization with Systemd

To run the RClone BiSync Manager as a systemd user service:

1. Copy the provided service file to your user systemd directory:

   ```bash
   mkdir -p ~/.config/systemd/user/
   cp rclone-bisync-manager.service ~/.config/systemd/user/
   ```

2. Reload the systemd daemon:

   ```bash
   systemctl --user daemon-reload
   ```

3. Start the service:

   ```bash
   systemctl --user start rclone-bisync-manager.service
   ```

4. Enable the service to start on login:

   ```bash
   systemctl --user enable rclone-bisync-manager.service
   ```

5. To stop the service:

   ```bash
   systemctl --user stop rclone-bisync-manager.service
   ```

6. To check the status:

   ```bash
   systemctl --user status rclone-bisync-manager.service
   ```

7. To view logs:

   ```bash
   journalctl --user -u rclone-bisync-manager.service
   ```

Note: To run the service when not logged in, enable lingering:

```bash
sudo loginctl enable-linger $USER
```

## Contributing

Contributions to the script are welcome. Please fork the repository, make your changes, and submit a pull request.

## License

Specify the license under which the script is released.

---

For more details on `rclone` and its capabilities, visit the [official RClone documentation](https://rclone.org/docs/).
