import argparse


def parse_args():
    parser = argparse.ArgumentParser(description="RClone BiSync Manager")
    parser.add_argument('-d', '--dry-run', action='store_true',
                        help='Perform a dry run without making any changes.')
    parser.add_argument('--console-log', action='store_true',
                        help='Print log messages to the console in addition to the log files.')

    subparsers = parser.add_subparsers(dest='command', required=True)

    # Daemon command
    daemon_parser = subparsers.add_parser('daemon', help='Run in daemon mode')
    daemon_parser.add_argument('action', choices=['start', 'stop', 'status'],
                               help='Action to perform on the daemon')

    # Sync command
    sync_parser = subparsers.add_parser(
        'sync', help='Perform a sync operation')
    sync_parser.add_argument('sync_jobs', nargs='*',
                             help='Specify sync jobs to run (optional, run all active jobs if not specified)')
    sync_parser.add_argument('--resync', action='store_true',
                             help='Force a resynchronization, ignoring previous sync status.')
    sync_parser.add_argument('--force-bisync', action='store_true',
                             help='Force the bisync operation without confirmation.')

    args = parser.parse_args()

    args.force_resync = args.command == 'sync' and args.resync
    args.specific_sync_jobs = args.sync_jobs if args.command == 'sync' and args.sync_jobs else None
    args.force_operation = args.command == 'sync' and args.force_bisync
    args.daemon_mode = args.command == 'daemon'

    return args
