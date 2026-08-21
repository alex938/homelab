"""Helpers for building throwaway git repositories in tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
    "HOME": "/tmp",
}


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=GIT_ENV,
        check=True,
    )
    return proc.stdout


def make_repo(path: Path, branch: str = "main") -> Path:
    """Create an empty git repository with an initial commit."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "--quiet", f"--initial-branch={branch}")
    (path / "README.md").write_text("logs\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "--quiet", "-m", "initial commit")
    return path


def add_log(repo: Path, service: str, filename: str, body: str) -> Path:
    """Write and commit a log file into a service folder."""
    folder = repo / service
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    target.write_text(body, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", f"{service}: {filename}")
    return target


SAMPLE_LOG = """\
=====================================================================
Security Onion Technician Session Log
=====================================================================

OUTCOME: NO ACTIVE FAULT FOUND. NO CHANGES MADE TO THE SERVER.

- Cluster health is GREEN with 235 active shards and none unassigned.
- Ingestion is real-time with sub-30s lag and advancing normally.
- Two salt-minion segfaults were seen at varying instruction pointers.

=====================================================================
ACTIONS REQUIRED FROM YOU (ALEX)
=====================================================================

PRIORITY 1 - HOST-SIDE HARDWARE TESTING on the physical KVM host.
PRIORITY 2 - ADD RAM TO THIS GUEST if that is possible at all.
PRIORITY 3 - DECISION NEEDED on elastalert Windows rule tuning.
"""
