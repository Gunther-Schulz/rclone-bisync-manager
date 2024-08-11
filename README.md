# RClone BiSync Manager

RClone BiSync Manager is a daemon-based solution for automated, bidirectional synchronization of files between local directories and remote storage supported by RClone. This Python script runs in the background, providing continuous synchronization with features such as periodic syncing, detailed logging, and real-time status reporting.

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

RClone BiSync Manager can operate in two modes: daemon mode and standalone mode.

### Daemon Mode

To start the RClone BiSync Manager daemon:

```bash
./rclone_bisync_manager.py --daemon
```

Daemon-specific commands:

- **--daemon**: Run the script in daemon mode.
- **--stop**: Stop the running daemon.
- **--status**: Get real-time status report from the daemon.
- **-d, --dry-run**: Perform a dry run without making actual changes.

Examples:

- Start the daemon: `./rclone_bisync_manager.py --daemon`
- Stop the daemon: `./rclone_bisync_manager.py --stop`
- Get daemon status: `./rclone_bisync_manager.py --status`

### Standalone Mode

In standalone mode, the script performs a single sync operation and then exits.

Command Line Options:

- **folders**: Specify particular folders to sync as a comma-separated list.
- **-d, --dry-run**: Perform a dry run without making actual changes.
- **--resync**: Force a resynchronization of specified folders.
- **--force-bisync**: Force a bisync operation (only when specific folders are specified).
- **--console-log**: Enable logging to the console in addition to log files.

Examples:

- Dry run for all folders: `./rclone_bisync_manager.py -d`
- Sync specific folders: `./rclone_bisync_manager.py documents,photos`
- Resync specific folders with console logging: `./rclone_bisync_manager.py documents,music --resync --console-log`
- Force bisync with console logging: `./rclone_bisync_manager.py photos --force-bisync --console-log`

## Configuration

The configuration file (`~/.config/rclone_bisync_manager/config.yaml`) contains all necessary settings for the synchronization process. Key configuration options include:

- `local_base_path`: Base path for local files to be synced
- `exclusion_rules_file`: File containing rules for excluding files/directories from sync
- `log_path`: Directory where log files will be stored
- `max_cpu_usage_percent`: CPU usage limit as a percentage
- `sync_paths`: Define the paths to be synchronized
- `rclone_options`: Customize rclone options
- `bisync_options`: Customize bisync-specific options
- `resync_options`: Customize resync-specific options

Refer to the comments in the example configuration file for detailed explanations of each option.

## Logs

Logs are stored in the directory specified in your configuration file. Check `rclone-bisync-manager-error.log` for errors and `rclone-bisync-manager.log` for detailed information.

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
