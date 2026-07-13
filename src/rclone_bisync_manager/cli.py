import argparse


def parse_args():
    parser = argparse.ArgumentParser(description="RClone BiSync Manager")
    parser.add_argument('--version', '-V', action='store_true',
                        help='Show version and exit.')

    # Global options
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument('--console-log', action='store_true',
                               help='Print log messages to the console in addition to the log files.')
    global_parser.add_argument('-d', '--dry-run', action='store_true',
                               help='Perform a dry run without making any changes.')
    global_parser.add_argument('--config', type=str,
                               help='Specify a custom config file location.')

    subparsers = parser.add_subparsers(dest='command', required=False)

    # Daemon command
    daemon_parser = subparsers.add_parser(
        'daemon', parents=[global_parser], help='Run in daemon mode')
    daemon_parser.add_argument('action', choices=['start', 'stop', 'status', 'reload'],
                               help='Action to perform on the daemon')

    # Sync command
    sync_parser = subparsers.add_parser(
        'sync', parents=[global_parser], help='Perform a sync operation')
    sync_parser.add_argument('sync_jobs', nargs='*',
                             help='Specify sync jobs to run (optional, run all active jobs if not specified)')
    sync_parser.add_argument('--resync', nargs='*', metavar='JOB_KEY',
                             help='Force a resynchronization for specified job(s), ignoring previous sync status.')
    sync_parser.add_argument('--force-bisync', action='store_true',
                             help='Pass --force to rclone, DISABLING the --max-delete safety '
                                  'check so an unlimited number of files may be deleted. This '
                                  'does not recover a job that needs a resync -- use --resync '
                                  'for that. Applies only to the job(s) named on this command.')

    # Add sync job command
    add_sync_parser = subparsers.add_parser('add-sync', parents=[global_parser],
                                            help='Add a sync job for immediate execution')
    add_sync_parser.add_argument(
        'sync_jobs', nargs='+', help='Names of the sync jobs to add')

    args = parser.parse_args()

    if getattr(args, 'version', False):
        return args
    if args.command is None:
        parser.error('the following arguments are required: command')

    return args
