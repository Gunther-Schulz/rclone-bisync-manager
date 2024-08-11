#!/bin/bash
systemctl stop rclone-bisync
systemctl daemon-reload
systemctl status rclone-bisync
systemctl start rclone-bisync
systemctl status rclone-bisync