#!/usr/bin/env python3

import sys

from rclone_bisync_manager.cli import parse_args
from rclone_bisync_manager.commands import run_command
from rclone_bisync_manager.config import config
from rclone_bisync_manager.logging_utils import log_error


def _get_version():
    try:
        from importlib.metadata import version
        return version("rclone-bisync-manager")
    except Exception:
        return "unknown"


def main():
    args = parse_args()

    if getattr(args, "version", False):
        print(_get_version())
        sys.exit(0)

    if args.config:
        config.set_config_file(args.config)
    else:
        config.set_config_file(config.default_config_file)

    print(f"Using config file: {config.config_file}")

    try:
        config.load_and_validate_config(args)
        print(f"Configuration loaded successfully from: {config.config_file}")
    except Exception as e:
        print(f"Error loading configuration: {str(e)}")
        sys.exit(1)

    result = run_command(args, config)
    if result is not None:
        sys.exit(result)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_error(f"Unhandled exception in main: {str(e)}")
        print(f"Unhandled exception: {str(e)}")
        sys.exit(1)
