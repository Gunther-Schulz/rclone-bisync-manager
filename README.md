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

### From Git Repository

1. Clone the repository:

   ```bash
   git clone https://github.com/yourusername/rclone-bisync.git
   cd rclone-bisync
   ```

2. Install required Python packages:

   ```bash
   pip install -r requirements.txt
   ```

3. Make the script executable:

   ```bash
   chmod +x rclone_bisync.py
   ```

4. Create the configuration directory:

   ```bash
   mkdir -p ~/.config/rclone_bisync
   ```

5. Copy the example configuration:

   ```bash
   cp config/config.yaml.example ~/.config/rclone_bisync/config.yaml
   ```

6. Edit the configuration file to suit your needs:
   ```bash
   nano ~/.config/rclone_bisync/config.yaml
   ```

### From AUR (Arch User Repository)

If you're using an Arch-based system, you can install rclone-bisync from the AUR:

1. Use your preferred AUR helper. For example, with `yay`:

   ```bash
   yay -S rclone-bisync
   ```

2. After installation, copy the example configuration:

   ```bash
   mkdir -p ~/.config/rclone-bisync
   cp /etc/rclone-bisync/config.yaml.example ~/.config/rclone-bisync/config.yaml
   ```

3. Edit the configuration file:
   ```bash
   nano ~/.config/rclone-bisync/config.yaml
   ```

## Configuration

The configuration file (`~/.config/rclone_bisync/config.yaml`) contains all necessary settings for the synchronization process. Refer to the comments in the example configuration file for detailed explanations of each option.

## Usage

### Manual Execution

Run the script using the following command:

```bash
./rclone_bisync.py [options]
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

- Dry run for all folders (recommended for initial testing): `./rclone_bisync.py -d`
- Dry run for specific folders: `./rclone_bisync.py documents,photos -d`
- Resync specific folders: `./rclone_bisync.py documents,music --resync`
- Force bisync with console logging: `./rclone_bisync.py photos --force-bisync --console-log`
- Run in daemon mode: `./rclone_bisync.py --daemon`
- Stop the daemon: `./rclone_bisync.py --stop`

It's highly recommended to always start with a dry run, especially when setting up the script for the first time or making changes to your configuration. This allows you to review the proposed changes without risking any data loss or unintended modifications.

Once you're confident that the dry run results are as expected, you can run the script without the `-d` or `--dry-run` option to perform the actual synchronization.

## Logs

Logs are stored in the directory specified in your configuration file. Check `rclone-bisync-error.log` for errors and `rclone-bisync.log` for detailed information.

## Handling Errors

If the script encounters critical errors, it logs them and may require manual intervention. Check the error log file `rclone-bisync-error.log` for concise information and the main logfile `rclone-bisync.log` for detailed information.

## Automating Synchronization with Systemd

To run the RClone BiSync script as a systemd user service:

1. Copy the provided service file to your user systemd directory:

   ```bash
   mkdir -p ~/.config/systemd/user/
   cp rclone-bisync.service ~/.config/systemd/user/
   ```

2. Reload the systemd daemon:

   ```bash
   systemctl --user daemon-reload
   ```

3. Start the service:

   ```bash
   systemctl --user start rclone-bisync.service
   ```

4. Enable the service to start on login:

   ```bash
   systemctl --user enable rclone-bisync.service
   ```

5. To stop the service:

   ```bash
   systemctl --user stop rclone-bisync.service
   ```

6. To check the status:

   ```bash
   systemctl --user status rclone-bisync.service
   ```

7. To view logs:
   ```bash
   journalctl --user -u rclone-bisync.service
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
