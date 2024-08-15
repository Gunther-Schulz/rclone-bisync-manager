import argparse


def parse_args():
    parser = argparse.ArgumentParser(description="RClone BiSync Manager")

    # Global options
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument('--console-log', action='store_true',
                               help='Print log messages to the console in addition to the log files.')
    global_parser.add_argument('-d', '--dry-run', action='store_true',
                               help='Perform a dry run without making any changes.')

    subparsers = parser.add_subparsers(dest='command', required=True)

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
                             help='Force the bisync operation without confirmation.')

    # Add sync job command
    add_sync_parser = subparsers.add_parser('add-sync', parents=[global_parser],
                                            help='Add a sync job for immediate execution')
    add_sync_parser.add_argument(
        'sync_jobs', nargs='+', help='Names of the sync jobs to add')

    args = parser.parse_args()

    args.force_resync = args.command == 'sync' and args.resync
    args.specific_sync_jobs = args.sync_jobs if args.command == 'sync' and args.sync_jobs else None
    args.force_operation = args.command == 'sync' and args.force_bisync
    args.daemon_mode = args.command == 'daemon'

    return args
