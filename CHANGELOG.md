# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0b1] - Beta (2025-02-02)

First beta release. Suitable for production use with backups; please report bugs.

### Added

- **Log rotation:** Configurable log rotation via `log_rotation_max_mb` and `log_rotation_backup_count` in config; uses Python's `RotatingFileHandler` instead of a custom file logger.
- **Environment helpers:** New `env_helpers.env_dir()` for consistent resolution of XDG and override paths; empty environment variables are treated as unset and fall back to defaults.
- **CLI version:** `--version` / `-V` flag prints version from `pyproject.toml` (via `importlib.metadata`).
- **Automated tests:** 42 pytest tests covering env helpers, config schema, scheduler (including missed jobs), sync state store, status protocol, runtime paths, status server, sync exit handling, and utils. Run with `pytest tests/ -v`.
- **Pre-commit hook:** Optional `githooks/pre-commit` runs pytest; install with `git config core.hooksPath githooks` (see DEV.md).
- **README:** Table of contents; "Setting up rclone (fresh system)"; development section; disclaimer on data loss and backups.

### Changed

- **Logging:** Config wrapper now correctly syncs `log_file_path` from `config.yaml` after validation; `Config.set_config_file` only initializes logging paths when config is not yet loaded.
- **Paths:** All path resolution (config, runtime, cache, state) uses `env_dir()` so that empty `XDG_*` or `RCLONE_BISYNC_MANAGER_RUNTIME_DIR` do not produce relative paths; fallback to user home is consistent.
- **README:** Restructured into Features, Requirements, Installation, Quick start, Configuration, Usage, System tray, Paths and environment, Desktop integration, Systemd service, Error handling and logging, Status server, Development, License. Corrected systemd service to use `rclone-bisync-manager` (not `.py`) in ExecStart/ExecStop.
- **DEV.md:** Cleaned up for clarity; Fish shell setup and debugging tips clarified.
- **TODO.md:** Trimmed; completed items moved to "Completed (reference)"; beta readiness checklist updated.

### Fixed

- **Scheduler:** When `run_missed_jobs: true`, the next future run no longer overwrites the already-scheduled missed run; missed jobs are now executed as intended.
- **Logging:** `ensure_log_file_path()` and tray `open_log_folder()` now check for non-empty directory to avoid misleading behavior.

### Project

- Version set to `0.3.0b1`; PyPI classifier `Development Status :: 4 - Beta`.
- Single source of truth for version: `pyproject.toml` `[project] version`.

---

## Earlier (alpha)

- **0.2.0a1** and prior: Alpha releases; initial daemon, tray, scheduler, and rclone bisync integration.

[Unreleased]: https://github.com/Gunther-Schulz/rclone-bisync-manager/compare/v0.3.0b1...HEAD
[0.3.0b1]: https://github.com/Gunther-Schulz/rclone-bisync-manager/compare/v0.2.0a1...v0.3.0b1
