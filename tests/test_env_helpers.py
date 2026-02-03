"""Tests for env_helpers.env_dir (empty = unset behavior)."""

import os

import pytest

from rclone_bisync_manager.env_helpers import env_dir


def test_env_dir_unset_returns_fallback():
    """Unset key returns fallback."""
    assert env_dir("_NONEXISTENT_KEY_XYZ", "fallback") == "fallback"


def test_env_dir_empty_string_returns_fallback():
    """Empty string is treated as unset."""
    os.environ["_TEST_ENV_DIR_EMPTY"] = ""
    try:
        assert env_dir("_TEST_ENV_DIR_EMPTY", "fallback") == "fallback"
    finally:
        os.environ.pop("_TEST_ENV_DIR_EMPTY", None)


def test_env_dir_whitespace_only_returns_fallback():
    """Whitespace-only value is treated as unset."""
    os.environ["_TEST_ENV_DIR_WS"] = "   \t  "
    try:
        assert env_dir("_TEST_ENV_DIR_WS", "fallback") == "fallback"
    finally:
        os.environ.pop("_TEST_ENV_DIR_WS", None)


def test_env_dir_set_returns_stripped_value():
    """Set key returns stripped value."""
    os.environ["_TEST_ENV_DIR_SET"] = "  /foo/bar  "
    try:
        assert env_dir("_TEST_ENV_DIR_SET", "fallback") == "/foo/bar"
    finally:
        os.environ.pop("_TEST_ENV_DIR_SET", None)


def test_env_dir_set_no_whitespace_returns_as_is():
    """Set key with no extra whitespace returns as is."""
    os.environ["_TEST_ENV_DIR_PLAIN"] = "/path"
    try:
        assert env_dir("_TEST_ENV_DIR_PLAIN", "fallback") == "/path"
    finally:
        os.environ.pop("_TEST_ENV_DIR_PLAIN", None)
