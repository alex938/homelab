"""Orchestration: pull the repo, find each service's newest log, summarise it.

``refresh()`` is the single entry point used by the web views, the management
command and the tests. It is safe to call repeatedly: a service whose newest log
has not changed is left alone, and no summariser process is spawned for it.
"""

from __future__ import annotations

import logging
import threading

from django.db import close_old_connections, transaction
from django.utils import timezone

from dashboard.models import LogSummary, RefreshState, Service
from dashboard.services import repo, summariser

logger = logging.getLogger(__name__)

_worker_lock = threading.Lock()
_worker: threading.Thread | None = None


class RefreshResult:
    """What one refresh pass did, for logging and for the API response."""

    def __init__(self) -> None:
        self.commit_sha: str = ""
        self.services: list[str] = []
        self.updated: list[str] = []
        self.unchanged: list[str] = []
        self.removed: list[str] = []
        self.errors: list[str] = []

    @property
    def changed(self) -> bool:
        return bool(self.updated or self.removed)

    def as_dict(self) -> dict:
        return {
            "commit_sha": self.commit_sha,
            "services": self.services,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "removed": self.removed,
            "errors": self.errors,
        }

    def summary_line(self) -> str:
        if self.errors:
            return f"Refreshed with {len(self.errors)} error(s)"
        if self.updated:
            return f"Updated {', '.join(self.updated)}"
        return f"Up to date ({len(self.services)} services)"


def refresh_service(service_name: str, force: bool = False) -> tuple[bool, str]:
    """Bring one service's summary in line with its newest log.

    Returns ``(updated, note)``.
    """
    log = repo.latest_log(service_name)
    now = timezone.now()

    service, _ = Service.objects.get_or_create(
        slug=service_name,
        defaults={"name": service_name, "first_seen": now, "last_seen": now},
    )
    Service.objects.filter(pk=service.pk).update(last_seen=now)

    if log is None:
        deleted, _ = LogSummary.objects.filter(service=service).delete()
        return bool(deleted), "no logs in folder"

    log_hash = log.content_hash()
    current = LogSummary.objects.filter(service=service).first()
    if current and current.log_hash == log_hash and not force:
        return False, "unchanged"

    body = log.read_text()
    result = summariser.summarise(service_name, log.filename, body)

    with transaction.atomic():
        # Only the newest log is ever displayed, so the previous summary goes.
        LogSummary.objects.filter(service=service).delete()
        LogSummary.objects.create(
            service=service,
            log_path=log.relative_path,
            log_filename=log.filename,
            log_hash=log_hash,
            log_bytes=log.size,
            commit_sha=log.commit_sha,
            commit_subject=log.commit_subject,
            logged_at=log.logged_at,
            status=result.status,
            headline=result.headline,
            key_points=result.key_points,
            actions=result.actions,
            summarised_at=timezone.now(),
            summariser=result.summariser,
            error=result.error,
        )
    return True, f"summarised {log.filename} via {result.summariser}"


def refresh(force: bool = False) -> RefreshResult:
    """Sync the repository and re-summarise every service that changed."""
    result = RefreshResult()
    result.commit_sha = repo.sync()

    found = repo.discover_services()
    result.services = list(found)

    for name in found:
        try:
            updated, note = refresh_service(name, force=force)
        except Exception as exc:  # a broken service must not hide the others
            logger.exception("refresh failed for %s", name)
            result.errors.append(repo.scrub(f"{name}: {exc}"))
            continue
        if updated:
            result.updated.append(name)
            logger.info("%s: %s", name, note)
        else:
            result.unchanged.append(name)

    # Services whose folder disappeared from the repository drop off the board.
    stale = Service.objects.exclude(slug__in=found)
    result.removed = list(stale.values_list("slug", flat=True))
    stale.delete()

    return result


def run_refresh_and_record(force: bool = False) -> RefreshResult:
    """Run a refresh, recording progress and outcome in :class:`RefreshState`."""
    state = RefreshState.load()
    state.running = True
    state.started_at = timezone.now()
    state.finished_at = None
    state.error = ""
    state.message = "Syncing logs repository..."
    state.save()

    result = RefreshResult()
    try:
        result = refresh(force=force)
        state.last_commit_sha = result.commit_sha
        state.message = result.summary_line()
        state.error = "\n".join(result.errors)
        if result.changed or force:
            state.version += 1
    except Exception as exc:
        logger.exception("refresh failed")
        state.message = "Refresh failed"
        state.error = repo.scrub(str(exc))
        result.errors.append(state.error)
    finally:
        state.running = False
        state.finished_at = timezone.now()
        state.last_checked_at = timezone.now()
        state.save()

    return result


def _worker_body(force: bool) -> None:
    close_old_connections()
    try:
        run_refresh_and_record(force=force)
    finally:
        close_old_connections()


def start_background_refresh(force: bool = False) -> bool:
    """Kick off a refresh in a thread. Returns False if one is already running."""
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return False
        thread = threading.Thread(
            target=_worker_body, args=(force,), name="logviewer-refresh", daemon=True
        )
        _worker = thread
        thread.start()
        return True


def is_refreshing() -> bool:
    with _worker_lock:
        return _worker is not None and _worker.is_alive()


def poll_remote_and_refresh_if_needed() -> bool:
    """Cheaply check the remote; start a refresh only if new commits exist.

    Called from the dashboard's polling endpoint, which is what makes newly
    committed logs appear without anyone pressing anything.
    """
    state = RefreshState.load()
    if state.running or is_refreshing() or not state.is_stale:
        return False

    try:
        changed, remote = repo.has_remote_changes()
    except repo.RepoError as exc:
        logger.warning("remote poll failed: %s", exc)
        state.last_checked_at = timezone.now()
        state.error = repo.scrub(str(exc))
        state.save()
        return False

    state.last_checked_at = timezone.now()
    state.save()

    if not changed and Service.objects.exists():
        return False
    return start_background_refresh()
