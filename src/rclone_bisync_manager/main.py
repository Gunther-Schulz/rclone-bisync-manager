#!/usr/bin/env python3

import sys

from rclone_bisync_manager.cli import parse_args
from rclone_bisync_manager.commands import run_command
from rclone_bisync_manager.config import get_config
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

    config = get_config()
    if args.config:
        config.set_config_file(args.config)
    else:
        config.set_config_file(config.default_config_file)

    print(f"Using config file: {config.config_file}")

    # `daemon status|stop|reload` only talk to the running daemon over its socket. Requiring a
    # valid config first meant a broken config -- or a local_base_path on an unmounted drive --
    # locked you out of inspecting or stopping the daemon at exactly the moment you needed to.
    talks_to_daemon_only = (
        getattr(args, "command", None) == "daemon"
        and getattr(args, "action", None) in ("status", "stop", "reload")
    )

    try:
        config.load_and_validate_config(args)
        print(f"Configuration loaded successfully from: {config.config_file}")
    except Exception as e:
        print(f"Error loading configuration: {str(e)}")
        if not talks_to_daemon_only:
            sys.exit(1)
        print(f"Continuing anyway: '{args.action}' does not need a valid config.")

    result = run_command(args, config)
    sys.exit(result if result is not None else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_error(f"Unhandled exception in main: {str(e)}")
        print(f"Unhandled exception: {str(e)}")
        sys.exit(1)
