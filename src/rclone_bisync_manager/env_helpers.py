"""Helpers for environment-based paths. Single source of truth for 'empty = unset' behavior."""

import os


def env_dir(key: str, fallback: str) -> str:
    """Return env value if set and non-empty (stripped), else fallback.

    Treats missing, empty string, and whitespace-only as unset (XDG-style).
    Non-string env values are treated as unset.
    """
    v = os.environ.get(key)
    if v is None or not isinstance(v, str) or not v.strip():
        return fallback
    return v.strip()
