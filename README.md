# RClone BiSync Script

This Python script provides a robust solution for bidirectional synchronization of files between a local directory and a remote storage supported by RClone. It includes features such as dry runs, forced resynchronization, detailed logging, and daemon mode for periodic syncing.

## Features

- **Bidirectional Synchronization**: Synchronize files between local and remote directories.
- **Dry Run Option**: Test synchronization without making actual changes.
- **Detailed Logging**: Log all operations, with separate logs for errors.
- **Configurable**: Configuration through a YAML file.
- **Signal Handling**: Graceful shutdown on SIGINT (CTRL-C).
- **Daemon Mode**: Run the script as a background process for periodic syncing.
- **Periodic Sync**: Set individual sync intervals for each sync path.

## Opinionated Settings

To keep the script running as robustly as possible, this script always uses the following settings:

- `--recover`: Attempts to recover from a failed sync.
- `--resilient`: Continues the sync even if some files can't be transferred.

## Prerequisites

Ensure you have `rclone` installed on your system along with other required tools like `mkdir`, `grep`, `awk`, `find`, and `md5sum`. These tools are necessary for the script to function correctly.

Optional: Install `cpulimit` if you want to use the CPU usage limiting feature. If `cpulimit` is not installed, the `max_cpu_usage_percent` setting in the configuration will be ignored.

For daemon mode, install the `python-daemon` package:

```bash
pip install python-daemon
```

## Installation

1. Clone the repository or download the script to your local machine.
2. Ensure that the script is executable:

```bash
chmod +x rclone_bisync.py
```

3. Create the configuration directory:

```bash
mkdir -p ~/.config/rclone_bisync
```

## Configuration

Before running the script, you must set up the configuration file (`~/.config/rclone_bisync/config.yaml`). This file contains all necessary settings for the synchronization process.

### Configuration File Structure

Here is a detailed explanation of the configuration file:

- **local_base_path**: The base directory on your local machine where synchronization folders are located.
- **exclusion_rules_file**: (Optional) Path to a file containing patterns to exclude from synchronization.
- **log_directory**: (Optional) Directory where log files will be stored. If not specified, defaults to `~/.cache/rclone/bisync/logs`.
- **max_cpu_usage_percent**: CPU usage limit as a percentage. This setting is only used if the optional dependency `cpulimit` is installed.
- **sync_paths**: A dictionary of synchronization pairs with details for local and remote directories.
- **rclone_options**: A dictionary of rclone options to be applied to all sync operations.
- **bisync_options**: A dictionary of bisync-specific options.
- **resync_options**: A dictionary of resync-specific options.

#### Example Configuration

```yaml
local_base_path: /home/g/hidrive
exclusion_rules_file: /home/g/hidrive/filter.txt
log_directory: /home/g/hidrive/logs
max_cpu_usage_percent: 100
sync_paths:
  documents:
    local: "Docs"
    rclone_remote: "remoteName"
    remote: "RemoteDocs"
    sync_interval: "daily"
  photos:
    local: "Photos"
    rclone_remote: "remoteName"
    remote: "RemotePhotos"
    sync_interval: "weekly"
rclone_options:
  max_delete: 5
  log_level: INFO
  max_lock: 15m
  retries: 3
  low_level_retries: 10
  compare: "size,modtime,checksum"
  create_empty_src_dirs: null
  check_access: null
  track_renames: null
bisync_options:
  conflict_resolve: newer
  conflict_loser: num
  conflict_suffix: rc-conflict
resync_options:
  error_on_no_transfer: null
  resync_mode: path1
```

### Important Notes

- **local_base_path**: This should be an absolute path.
- **exclusion_rules_file**: This file should contain one pattern per line, which defines which files to exclude from sync. For more details refer to the rclone documenatation. Example:

```bash
.*\.txt$
.*\.doc$
```

- **sync_paths**: Each entry under this key represents a pair of directories to be synchronized. `local` is a subdirectory under `local_base_path`, and `remote` is the path on the remote storage.
- **sync_interval**: This is an optional field that specifies the interval for periodic syncing. If not provided, the path will not be synced automatically in daemon mode.
- **rclone_options**, **bisync_options**, and **resync_options**: These allow you to customize various aspects of the sync operation. Refer to the rclone documentation for details on available options.
- The `resync` option in `bisync_options` is ignored if set in the config file. Use the command-line argument `--resync` to trigger a resync operation.
- Options that don't accept parameters (like `track_renames`, `create_empty_src_dirs`, etc.) should be set to `null` in the configuration file.

The following settings are not configurable and are always used:

- `resync`
- `log-file`
- `recover`
- `resilient`

## Usage

Before running any synchronization operations, it's strongly recommended to perform a dry run first to ensure everything is set up correctly and to preview the changes that would be made.

Run the script using the following command:

```bash
python rclone_bisync.py [options]
```

### Command Line Options

- **folders**: Specify particular folders to sync as a comma-separated list (optional). If not provided, all sync paths will be synced.
- **-d, --dry-run**: Perform a dry run. Use this option to safely test your configuration without making any actual changes.
- **--resync**: Force a resynchronization.
- **--force-bisync**: Force a bisync. This option is only applicable if specific folders are specified.
- **--console-log**: Enable logging to the console. Only wrapper messages are logged to the console, not the detailed log messages from rclone.
- **--daemon**: Run the script in daemon mode for periodic syncing.
- **--stop**: Stop the daemon if it's running.

Examples:

- Dry run for all folders (recommended for initial testing): `python rclone_bisync.py -d`
- Dry run for specific folders: `python rclone_bisync.py documents,photos -d`
- Resync specific folders: `python rclone_bisync.py documents,music --resync`
- Force bisync with console logging: `python rclone_bisync.py photos --force-bisync --console-log`
- Run in daemon mode: `python rclone_bisync.py --daemon`
- Stop the daemon: `python rclone_bisync.py --stop`

It's highly recommended to always start with a dry run, especially when setting up the script for the first time or making changes to your configuration. This allows you to review the proposed changes without risking any data loss or unintended modifications.

Once you're confident that the dry run results are as expected, you can run the script without the `-d` or `--dry-run` option to perform the actual synchronization.

## Logs

Logs are stored in the `logs` directory within the base directory specified in the configuration file. There are separate logs for general operations and errors.

## Handling Errors

If the script encounters critical errors, it logs them and may require manual intervention. Check the error log file `rclone-bisync-error.log` for concise information and the main logfile `rclone-bisync.log` for detailed information.

## Automating Synchronization with Systemd

To run the RClone BiSync script as a systemd service, follow these steps:

1. Create a systemd service file named `rclone-bisync.service` in `/etc/systemd/system/`:

```ini
[Unit]
Description=Rclone Bisync Daemon
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/rclone-bisync.py --daemon
User=your_username
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

2. Reload the systemd daemon and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl start rclone-bisync
```

3. To enable the service to start automatically on boot:

```bash
sudo systemctl enable rclone-bisync
```

4. To stop the service:

```bash
sudo systemctl stop rclone-bisync
```

5. To check the status of the service:

```bash
sudo systemctl status rclone-bisync
```

This setup allows you to run your rclone bisync script as a systemd service, which will automatically start on boot and restart if it fails.

## Contributing

Contributions to the script are welcome. Please fork the repository, make your changes, and submit a pull request.

## License

Specify the license under which the script is released.

---

For more details on `rclone` and its capabilities, visit the [official RClone documentation](https://rclone.org/docs/).
