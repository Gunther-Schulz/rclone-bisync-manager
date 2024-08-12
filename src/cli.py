import argparse
from config import dry_run, force_resync, console_log, specific_sync_jobs, force_operation, daemon_mode


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

    global dry_run, force_resync, console_log, specific_sync_jobs, force_operation, daemon_mode
    dry_run = args.dry_run
    console_log = args.console_log

    if args.command == 'sync':
        force_resync = args.resync
        specific_sync_jobs = args.sync_jobs if args.sync_jobs else None
        force_operation = args.force_bisync
        daemon_mode = False
    elif args.command == 'daemon':
        force_resync = False
        specific_sync_jobs = None
        force_operation = False
        daemon_mode = True

    return args
