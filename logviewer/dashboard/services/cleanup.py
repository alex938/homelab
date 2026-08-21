"""Disk-usage reporting and housekeeping.

Nothing here is required for the dashboard to work: pruning already happens
automatically (transcripts after every summarisation, git maintenance after
every sync). This module exists so the growth can be inspected and forced.
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

from dashboard.services import repo, summariser

logger = logging.getLogger(__name__)


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"  # pragma: no cover - unreachable


def usage() -> dict[str, int]:
    """Bytes on disk for everything this app creates."""
    data_dir = Path(settings.DATA_DIR)
    clone = repo.repo_dir()
    return {
        "clone_worktree": repo.directory_size(clone) - repo.directory_size(clone / ".git"),
        "clone_git": repo.directory_size(clone / ".git"),
        "database": repo.directory_size(data_dir / "db.sqlite3"),
        "staticfiles": repo.directory_size(data_dir / "staticfiles"),
        "claude_transcripts": repo.directory_size(summariser.transcript_dir()),
    }


def transcript_count() -> int:
    folder = summariser.transcript_dir()
    if not folder.is_dir():
        return 0
    return len(list(folder.glob("*.jsonl")))


def run(dry_run: bool = False) -> dict:
    """Prune what can be pruned. Returns a before/after report."""
    before = usage()
    transcripts_before = transcript_count()

    if dry_run:
        return {
            "dry_run": True,
            "before": before,
            "after": before,
            "transcripts_removed": 0,
            "transcripts_prunable": max(
                transcripts_before - max(settings.CLAUDE_TRANSCRIPT_KEEP, 0), 0
            ),
        }

    removed = summariser.prune_transcripts()
    if repo.is_cloned():
        repo.maintain()

    return {
        "dry_run": False,
        "before": before,
        "after": usage(),
        "transcripts_removed": removed,
        "transcripts_prunable": 0,
    }
