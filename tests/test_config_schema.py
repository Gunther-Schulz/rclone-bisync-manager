"""Tests for config schema validation (ConfigSchema, SyncJobConfig, disallowed keys)."""

import tempfile
from pathlib import Path

import pytest

from rclone_bisync_manager.config import ConfigSchema, SyncJobConfig
from pydantic import ValidationError


def _minimal_sync_jobs(local_base_path: str) -> dict:
    return {
        "job1": {
            "local": "subdir",
            "rclone_remote": "remote",
            "remote": "path/on/remote",
            "schedule": "0 * * * *",
        }
    }


def test_config_schema_valid_minimal(tmp_path: Path):
    """Valid minimal config loads."""
    data = {
        "local_base_path": str(tmp_path),
        "sync_jobs": _minimal_sync_jobs(str(tmp_path)),
    }
    schema = ConfigSchema(**data)
    assert schema.local_base_path == tmp_path
    assert "job1" in schema.sync_jobs
    assert schema.sync_jobs["job1"].schedule == "0 * * * *"


def test_config_schema_sync_job_without_schedule_valid(tmp_path: Path):
    """Sync job without schedule is valid (manual-only job)."""
    data = {
        "local_base_path": str(tmp_path),
        "sync_jobs": {
            "job1": {
                "local": "subdir",
                "rclone_remote": "remote",
                "remote": "path/on/remote",
            }
        },
    }
    schema = ConfigSchema(**data)
    assert schema.sync_jobs["job1"].schedule is None


def test_config_schema_invalid_cron_rejected():
    """Invalid cron string raises ValidationError."""
    with tempfile.TemporaryDirectory() as d:
        data = {
            "local_base_path": d,
            "sync_jobs": {
                "job1": {
                    "local": "sub",
                    "rclone_remote": "r",
                    "remote": "p",
                    "schedule": "not-a-cron",
                }
            },
        }
        with pytest.raises(ValidationError):
            ConfigSchema(**data)


def test_sync_job_options_disallowed_keys_rejected():
    """rclone_options with disallowed key raises ValidationError."""
    with tempfile.TemporaryDirectory() as d:
        data = {
            "local_base_path": d,
            "sync_jobs": {
                "job1": {
                    "local": "sub",
                    "rclone_remote": "r",
                    "remote": "p",
                    "schedule": "0 0 * * *",
                    "rclone_options": {"resync": True},
                }
            },
        }
        with pytest.raises(ValidationError) as exc_info:
            ConfigSchema(**data)
        assert "not allowed" in str(exc_info.value).lower() or "resync" in str(exc_info.value)


def test_sync_job_options_log_file_disallowed():
    """rclone_options with 'log-file' raises ValidationError."""
    with tempfile.TemporaryDirectory() as d:
        data = {
            "local_base_path": d,
            "sync_jobs": {
                "job1": {
                    "local": "sub",
                    "rclone_remote": "r",
                    "remote": "p",
                    "schedule": "0 0 * * *",
                    "rclone_options": {"log-file": "/tmp/x"},
                }
            },
        }
        with pytest.raises(ValidationError):
            ConfigSchema(**data)
