# RClone BiSync Manager

RClone BiSync Manager is a daemon-based solution for automated, bidirectional synchronization of files between local directories and remote storage supported by RClone. This Python script runs in the background, providing continuous synchronization with features such as periodic syncing, detailed logging, and real-time status reporting.

## Key Features

- **Daemon-based Operation**: Runs continuously in the background, managing synchronization tasks without user intervention.
- **Periodic Synchronization**: Automatically syncs files based on user-defined schedules for each sync job.
- **Real-time Status Reporting**: Provides up-to-date information on sync operations and daemon status.
- **Dynamic Configuration Reloading**: Automatically detects and applies configuration changes without restarting the daemon.
- **Graceful Shutdown Handling**: Ensures clean termination of sync operations when stopping the daemon.
- **Flexible Sync Options**: Supports both bisync and resync operations with customizable options.
- **Dry Run Option**: Test synchronization without making actual changes.
- **Detailed Logging**: Separate logs for general operations and errors.
- **CPU Usage Limiting**: Option to limit CPU usage during sync operations (requires cpulimit).
- **Hash Warning Detection**: Identifies and logs hash warnings during sync operations.
- **Conflict Resolution**: Supports automatic conflict resolution for sync conflicts.
- **Recovery Mode**: Allows robust recovery from interruptions without requiring a full resync.

## Prerequisites

- Python 3.6+
- `rclone` (required)
- `cpulimit` (optional, for CPU usage limiting)
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
   mkdir -p ~/.config/rclone-bisync-manager
   cp config.yaml.example ~/.config/rclone-bisync-manager/config.yaml
   ```

4. Edit the configuration file to suit your needs:

   ```bash
   nano ~/.config/rclone-bisync-manager/config.yaml
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

### Sync Mode

In sync mode, the script performs a single sync operation and then exits:

```bash
./rclone_bisync_manager.py sync [sync_jobs] [options]
```

Options:

- **sync_jobs**: Specify particular sync jobs to run (optional, syncs all if not specified).
- **--resync**: Force a resynchronization of specified sync jobs.
- **--force-bisync**: Force a bisync operation without confirmation.

Examples:

- Sync all jobs: `./rclone_bisync_manager.py sync`
- Sync specific jobs: `./rclone_bisync_manager.py sync job1 job2`
- Force resync of a job: `./rclone_bisync_manager.py sync job1 --resync`

### Add Sync Job

To add a sync job for immediate execution while the daemon is running:

```bash
./rclone_bisync_manager.py add-sync job1 [job2 ...]
```

## Configuration

The configuration file (`~/.config/rclone-bisync-manager/config.yaml`) contains all necessary settings for the synchronization process. Key configuration options include:

- `local_base_path`: Base path for local files to be synced
- `exclusion_rules_file`: File containing rules for excluding files/directories from sync
- `redirect_rclone_log_output`: Redirect rclone log output to the main log file
- `max_cpu_usage_percent`: CPU usage limit as a percentage
- `run_missed_jobs`: Whether to run missed jobs on startup
- `run_initial_sync_on_startup`: Whether to perform an initial sync when the daemon starts
- `sync_jobs`: Define the paths to be synchronized
- `rclone_options`: Customize global rclone options
- `bisync_options`: Customize global bisync-specific options
- `resync_options`: Customize global resync-specific options

Refer to the comments in the example configuration file for detailed explanations of each option.

### Per-Job Configuration

You can override global rclone, bisync, and resync options on a per-job basis. This allows for fine-tuned control over each sync job. To do this, add `rclone_options`, `bisync_options`, or `resync_options` under a specific job in the `sync_jobs` section. For example:

```yaml
sync_jobs:
  example_job:
    local: example_folder
    rclone_remote: your_remote
    remote: path/on/remote/storage
    schedule: "*/30 * * * *"
    dry_run: false
    rclone_options:
      transfers: 4
      checkers: 8
    bisync_options:
      resync: true
    resync_options:
      create_empty_src_dirs: true
```

In this example, the `example_job` uses custom rclone, bisync, and resync options that will override the global settings for this specific job.

## Logs

Logs are stored in the default log directory:

```
~/.local/state/rclone-bisync-manager/logs/
```

This directory contains two main log files:

- `rclone-bisync-manager.log`: Contains detailed information about sync operations.
- `rclone-bisync-manager-error.log`: Contains error messages and warnings.

## Contributing

Contributions to the script are welcome. Please fork the repository, make your changes, and submit a pull request.

## License

[Specify the license under which the script is released]

---

For more details on `rclone` and its capabilities, visit the [official RClone documentation](https://rclone.org/docs/).
