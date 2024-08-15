#!/usr/bin/env python3

import subprocess
import time
import os
import psutil


def is_daemon_running():
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            if proc.name() == 'python' and any('rclone-bisync-manager' in arg for arg in proc.cmdline()):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False


def start_daemon():
    if is_daemon_running():
        print("Daemon is already running")
        return

    print("Starting daemon...")
    command = ["rclone-bisync-manager", "daemon", "start"]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        preexec_fn=os.setpgrp
    )

    time.sleep(2)  # Give the daemon some time to start

    if process.poll() is None:
        print("Daemon start command is still running")
    else:
        stdout, stderr = process.communicate()
        print(f"Daemon start command exited with return code: {
              process.returncode}")
        if stdout:
            print(f"Stdout: {stdout}")
        if stderr:
            print(f"Stderr: {stderr}")

    if is_daemon_running():
        print("Daemon is now running")
    else:
        print("Daemon failed to start")


def stop_daemon():
    if not is_daemon_running():
        print("Daemon is not running")
        return

    print("Stopping daemon...")
    command = ["rclone-bisync-manager", "daemon", "stop"]

    result = subprocess.run(command, capture_output=True, text=True)

    print(f"Stop command exit code: {result.returncode}")
    if result.stdout:
        print(f"Stdout: {result.stdout}")
    if result.stderr:
        print(f"Stderr: {result.stderr}")

    time.sleep(2)  # Give the daemon some time to stop

    if is_daemon_running():
        print("Daemon is still running")
    else:
        print("Daemon has been stopped")


def main():
    while True:
        print("\n1. Start Daemon")
        print("2. Stop Daemon")
        print("3. Check Daemon Status")
        print("4. Exit")
        choice = input("Enter your choice (1-4): ")

        if choice == '1':
            start_daemon()
        elif choice == '2':
            stop_daemon()
        elif choice == '3':
            if is_daemon_running():
                print("Daemon is running")
            else:
                print("Daemon is not running")
        elif choice == '4':
            break
        else:
            print("Invalid choice. Please try again.")


if __name__ == "__main__":
    main()
