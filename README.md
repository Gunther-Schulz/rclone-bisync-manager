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
  - croniter
  - pydantic

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

RClone BiSync Manager can operate in three modes: daemon mode, sync mode, and add-sync mode.

### Global Options

These options can be used with any command:

- **-d, --dry-run**: Perform a dry run without making actual changes.
- **--console-log**: Enable logging to the console in addition to log files.

### Daemon Mode

To manage the RClone BiSync Manager daemon:

```bash
./rclone_bisync_manager.py daemon [start|stop|status|reload]
```

Examples:

- Start the daemon: `./rclone_bisync_manager.py daemon start`
- Stop the daemon: `./rclone_bisync_manager.py daemon stop`
- Get daemon status: `./rclone_bisync_manager.py daemon status`
- Reload daemon configuration: `./rclone_bisync_manager.py daemon reload`

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

### Sync Job Configuration

Each sync job in the `sync_jobs` section of the configuration file should have the following structure:

```yaml
sync_jobs:
  job_name:
    local: "local_folder_name"
    rclone_remote: "remote_name"
    remote: "path/on/remote/storage"
    schedule: "*/30 * * * *"
    active: true
    dry_run: false
    force_resync: false
    force_operation: false
    rclone_options:
      option1: value1
    bisync_options:
      option2: value2
    resync_options:
      option3: value3
```

- `job_name`: A unique identifier for the sync job
- `local`: The name of the local folder to sync (relative to `local_base_path`)
- `rclone_remote`: The name of the rclone remote to use
- `remote`: The path on the remote storage
- `schedule`: A cron-style schedule for when to run the sync job
- `active`: Whether the job is active (true/false)
- `dry_run`: Whether to perform a dry run for this job (true/false)
- `force_resync`: Whether to force a resync for this job (true/false)
- `force_operation`: Whether to force the operation without confirmation (true/false)
- `rclone_options`, `bisync_options`, `resync_options`: Job-specific options that override global settings

## Logs

Logs are stored in the default log directory:

```
~/.local/state/rclone-bisync-manager/logs/rclone-bisync-manager.log
```

## Advanced Usage

### Reloading Configuration

You can reload the configuration without restarting the daemon:

```bash
./rclone_bisync_manager.py daemon reload
```

### Checking Daemon Status

To get detailed status information about the running daemon:

```bash
./rclone_bisync_manager.py daemon status
```

This will provide information about running jobs, queued jobs, and any configuration errors.

### Managing Sync Jobs

You can add new sync jobs to a running daemon:

```bash
./rclone_bisync_manager.py add-sync new_job_name
```

This will trigger an immediate sync for the new job and add it to the scheduled tasks.

## Setting Up a New Share

To set up a new share for synchronization, follow these steps:

1. Ensure you have rclone configured with the remote you want to use. If not, set it up using `rclone config`.

2. Add a new sync job to your configuration file (`~/.config/rclone-bisync-manager/config.yaml`):

   ```yaml
   sync_jobs:
     new_share:
       local: "LocalFolderName"
       rclone_remote: "YourRemoteName"
       remote: "path/on/remote/storage"
       schedule: "*/30 * * * *"
       active: true
   ```

3. Create the RCLONE_TEST file in both the local and remote locations. This file is used to verify the connection and permissions. Replace `<path>` with your actual paths:

   For local:

   ```bash
   rclone touch "/path/to/your/local/base/directory/LocalFolderName/RCLONE_TEST"
   ```

   For remote:

   ```bash
   rclone touch "YourRemoteName:path/on/remote/storage/RCLONE_TEST"
   ```

4. Perform an initial sync to ensure everything is set up correctly:

   ```bash
   ./rclone_bisync_manager.py sync new_share --resync
   ```

5. If the initial sync is successful, you can start the daemon (if it's not already running) to begin automatic synchronization:

   ```bash
   ./rclone_bisync_manager.py daemon start
   ```

Remember to replace "LocalFolderName", "YourRemoteName", and "path/on/remote/storage" with your actual folder names and paths.

### Troubleshooting RCLONE_TEST File Issues

If you encounter issues with the RCLONE_TEST file:

1. Ensure you have write permissions on both the local and remote locations.
2. Check if the file exists using `rclone lsf`:
   ```bash
   rclone lsf "/path/to/your/local/base/directory/LocalFolderName"
   rclone lsf "YourRemoteName:path/on/remote/storage"
   ```
3. If the file doesn't exist or you can't create it, check your rclone configuration and permissions for the remote storage.

For more detailed information on rclone commands and troubleshooting, refer to the [official rclone documentation](https://rclone.org/docs/).

## Troubleshooting

- If you encounter "hash unexpectedly blank" warnings, you may need to use the `--ignore-size` option in your rclone configuration for the affected job.
- Check the log file for detailed error messages and sync operation statuses.
- Use the `--dry-run` option to test your configuration without making actual changes.

## Contributing

Contributions to the script are welcome. Please fork the repository, make your changes, and submit a pull request.

## License

[Specify the license under which the script is released]

---

For more details on `rclone` and its capabilities, visit the [official RClone documentation](https://rclone.org/docs/).
