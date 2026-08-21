"""Minimal .env loader.

Kept dependency-free on purpose: the app is meant to run from a bare virtualenv
with nothing but Django installed.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    """Parse a ``KEY=value`` file and merge it into ``os.environ``.

    Values already present in the real environment win, so a deployment can
    override the file without editing it. Returns the values parsed from the
    file itself (not the merged environment) to make the loader easy to test.
    """
    parsed: dict[str, str] = {}
    if not path.is_file():
        return parsed

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key:
            continue
        parsed[key] = value
        os.environ.setdefault(key, value)

    return parsed
