"""A change to ANY filter input must force a resync first.

If it doesn't, the newly-excluded files vanish from rclone's listings, bisync reads them as
deletions, and deletes them for real on the other side.
"""

import pytest

from rclone_bisync_manager.utils import compute_filter_fingerprint


class FakeJob:
    def __init__(self, rclone_options=None, bisync_options=None, resync_options=None):
        self.rclone_options = rclone_options or {}
        self.bisync_options = bisync_options or {}
        self.resync_options = resync_options or {}


class FakeConfig:
    def __init__(self, exclusion_rules_file=None, rclone_options=None,
                 bisync_options=None, resync_options=None):
        self.exclusion_rules_file = exclusion_rules_file
        self.rclone_options = rclone_options or {}
        self.bisync_options = bisync_options or {}
        self.resync_options = resync_options or {}


def test_changing_the_exclude_option_changes_the_fingerprint():
    """The gap that neither rclone nor the old MD5 file check covered: rclone does not track
    --exclude changes, and the old check only hashed the filters file."""
    before = compute_filter_fingerprint(FakeJob(), FakeConfig(rclone_options={"exclude": ["*.tmp"]}))
    after = compute_filter_fingerprint(
        FakeJob(), FakeConfig(rclone_options={"exclude": ["*.tmp", "*.iso"]}))
    assert before != after


def test_changing_the_filters_file_changes_the_fingerprint(tmp_path):
    rules = tmp_path / "filter.txt"
    rules.write_text("- *.tmp\n")
    before = compute_filter_fingerprint(FakeJob(), FakeConfig(exclusion_rules_file=str(rules)))
    rules.write_text("- *.tmp\n- *.iso\n")
    after = compute_filter_fingerprint(FakeJob(), FakeConfig(exclusion_rules_file=str(rules)))
    assert before != after


def test_a_job_level_filter_change_changes_the_fingerprint():
    before = compute_filter_fingerprint(FakeJob(), FakeConfig())
    after = compute_filter_fingerprint(FakeJob(rclone_options={"exclude": ["*.iso"]}), FakeConfig())
    assert before != after


def test_min_size_counts_as_a_filter():
    """--min-size also decides which files are listed, so changing it can look like deletions."""
    before = compute_filter_fingerprint(FakeJob(), FakeConfig())
    after = compute_filter_fingerprint(FakeJob(), FakeConfig(rclone_options={"min_size": "1M"}))
    assert before != after


def test_non_filter_options_do_not_force_a_resync():
    """A resync of a large remote is expensive: only filter changes may trigger one."""
    before = compute_filter_fingerprint(FakeJob(), FakeConfig(rclone_options={"log_level": "INFO"}))
    after = compute_filter_fingerprint(
        FakeJob(), FakeConfig(rclone_options={"log_level": "DEBUG", "retries": 5}))
    assert before == after


def test_fingerprint_is_stable_for_unchanged_config(tmp_path):
    """Must not drift between runs, or every job would resync forever."""
    rules = tmp_path / "filter.txt"
    rules.write_text("- *.tmp\n")
    cfg = FakeConfig(exclusion_rules_file=str(rules), rclone_options={"exclude": ["*.log"]})
    assert compute_filter_fingerprint(FakeJob(), cfg) == compute_filter_fingerprint(FakeJob(), cfg)


def test_underscore_and_hyphen_spellings_are_the_same_filter():
    """min_size and min-size are the same rclone flag; they must not look like a change."""
    a = compute_filter_fingerprint(FakeJob(), FakeConfig(rclone_options={"min_size": "1M"}))
    b = compute_filter_fingerprint(FakeJob(), FakeConfig(rclone_options={"min-size": "1M"}))
    assert a == b
