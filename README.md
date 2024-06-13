# RClone BiSync Script

This Python script provides a robust solution for bidirectional synchronization of files between a local directory and a remote storage supported by RClone. It includes features such as dry runs, forced resynchronization, and detailed logging.

## Features

- **Bidirectional Synchronization**: Synchronize files between local and remote directories.
- **Dry Run Option**: Test synchronization without making actual changes.
- **Forced Resynchronization**: Ignore previous sync statuses and force a new sync.
- **Detailed Logging**: Log all operations, with separate logs for errors.
- **Configurable**: Configuration through a YAML file.
- **Signal Handling**: Graceful shutdown on SIGINT (CTRL-C).

## Prerequisites

Ensure you have `rclone` installed on your system along with other required tools like `mkdir`, `grep`, `awk`, `find`, and `md5sum`. These tools are necessary for the script to function correctly.

## Installation

1. Clone the repository or download the script to your local machine.
2. Ensure that the script is executable:

```bash
chmod +x rclone_bisync.py
```

## Configuration

Before running the script, you must set up the configuration file (`rclone_bisync.yaml`). This file contains all necessary settings for the synchronization process.

### Configuration File Structure

Here is a detailed explanation of the configuration file:

- **sync_base_dir**: The base directory on your local machine where synchronization folders are located.
- **filter_file**: Path to a file containing patterns to exclude from synchronization.
- **max_delete**: Maximum percentage of files that can be deleted in one sync operation (to prevent massive accidental deletions).
- **sync_dirs**: A dictionary of synchronization pairs with details for local and remote directories.

#### Example Configuration

```yaml
sync_base_dir: "/path/to/local/sync/directory"
filter_file: "/path/to/filter/file"
max_delete: 50 # Allows up to 50% of files to be deleted
log_dir: "/path/to/log/directory"
sync_dirs:
  documents:
    local: "Docs"
    rclone_remote: "remoteName"
    remote: "RemoteDocs"
```

### Important Notes

- **sync_base_dir**: This should be an absolute path.
- **filter_file**: This file should contain one pattern per line, which defines which files to exclude from sync. For me details refer to the rclone documenatation. Example:

```bash
.*\.txt$
.*\.doc$
```

- **sync_dirs**: Each entry under this key represents a pair of directories to be synchronized. `local` is a subdirectory under `sync_base_dir`, and `remote` is the path on the remote storage.

## Usage

Run the script using the following command:

```bash
python rclone_bisync.py [options]
```

### Command Line Options

- **folder**: Specify a particular folder to sync (optional).
- **-d, --dry-run**: Perform a dry run.
- **--resync**: Force a resynchronization.
- **--force-bisync**: Force a bisync. This option is only applicable if a specific folder is specified.
- **--console-log**: Enable logging to the console. Only wrapper messages are logged to the console, not the detailed log messages from rclone.

## Logs

Logs are stored in the `logs` directory within the base directory specified in the configuration file. There are separate logs for general operations and errors.

## Handling Errors

If the script encounters critical errors, it logs them and may require manual intervention. Check the error log file `sync_error.log` for concise information and the main logfile `sync.log` for detailed information.

## Automating Synchronization with Cron (Example)

To run the RClone BiSync script periodically, you can use a cron job on Unix-like systems. Here's how you can set it up:

1. **Open the crontab for editing**:
   Open your terminal and type the following command to edit the crontab file:

```bash
crontab -e
```

2. **Add a cron job**:
   In the crontab file, add a line that specifies how often you want the script to run. For example, to run the synchronization every day at 3 AM, you would add:

```bash
0 3 /usr/bin/python /home/user/rclone_bisync.py 2>&1
```

- `0 * * * *` - Cron schedule expression that means "at the start of every hour".
- `/usr/bin/python` - Path to your Python executable. This might be different like `/usr/local/bin/python3` depending on your installation.
- `/home/user/rclone_bisync.py` - Full path to your script.

3. **Save and close the crontab**:
   Save the changes and exit the editor. The cron service will automatically pick up the new job and run it at the scheduled times.

4. **Check that the cron job is set**:
   To list all your cron jobs, you can type:

### Handling Missed Cron Jobs with Anacron

For systems that are not running 24/7, such as laptops or desktops, you might miss scheduled tasks if the system is off. To handle this, you can use `anacron`, which runs missed tasks as soon as the system is back online.

1. **Install Anacron** (if not already installed):

Instruction for Debian based systems:

```bash
sudo apt-get install anacron
```

Instruction for Arch based systems:

```bash
sudo pacman -S anacron
```

2. **Configure Anacron**:
   Edit the `anacrontab` file to add your job:

```bash
sudo nano /etc/anacrontab
```

Add the following line to schedule your synchronization script:

```bash
1 5 rclone_sync /usr/bin/python /home/user/rclone_bisync.py
```

- `1` - Run once a day.
- `5` - Delay in minutes after startup before the task is run.
- `rclone_sync` - A unique identifier for the job.
- The command is the full path to your script.

3. **Save and Exit**:
   After adding the job, save your changes and close the editor. Anacron will automatically handle running this job daily, including after a delay if the system was off at the scheduled time.

4. **Verify Anacron Jobs**:
   To see the list of anacron jobs, you can view the `anacrontab` file:

```bash
cat /etc/anacrontab
```

This setup ensures that your synchronization tasks are executed at least once every day, even if the computer is turned off at the scheduled time.

## Contributing

Contributions to the script are welcome. Please fork the repository, make your changes, and submit a pull request.

## License

Specify the license under which the script is released.

---

For more details on `rclone` and its capabilities, visit the [official RClone documentation](https://rclone.org/docs/).
