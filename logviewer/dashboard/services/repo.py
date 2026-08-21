"""Access to the GitLab repository that holds the agent logs.

Everything here shells out to ``git``. The access token is only ever placed in
the URL passed to a subprocess argument list (never a shell string) and is
scrubbed from any error text before it can reach a template or a log line.
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from django.conf import settings

logger = logging.getLogger(__name__)

GIT_TIMEOUT = 120

# ``execute-20260821-090820.log`` -> 2026-08-21 09:08:20
FILENAME_TIMESTAMP = re.compile(r"(\d{8})[-_T](\d{6})")
FILENAME_DATE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")


class RepoError(RuntimeError):
    """A git operation failed."""


@dataclass(frozen=True)
class LogFile:
    """One log file inside a service folder."""

    service: str
    path: Path
    relative_path: str
    filename: str
    size: int
    logged_at: datetime | None
    commit_sha: str = ""
    commit_subject: str = ""

    def read_text(self) -> str:
        return self.path.read_text(encoding="utf-8", errors="replace")

    def content_hash(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


def scrub(text: str) -> str:
    """Remove the access token from any text that might be displayed."""
    token = settings.GITLAB_ACCESS_TOKEN
    if token:
        text = text.replace(token, "***")
    # Also catch ``https://user:secret@host`` forms built elsewhere.
    return re.sub(r"(https?://)[^/\s@]+@", r"\1***@", text)


def authenticated_url(url: str | None = None) -> str:
    """Return the repository URL with the access token embedded, if there is one."""
    url = url or settings.LOGS_REPO_URL
    token = settings.GITLAB_ACCESS_TOKEN
    if not token or not url.startswith("http"):
        return url
    parts = urlsplit(url)
    if "@" in parts.netloc:
        return url
    user = quote(settings.GITLAB_TOKEN_USERNAME, safe="")
    netloc = f"{user}:{quote(token, safe='')}@{parts.netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def run_git(args: list[str], cwd: Path | None = None, timeout: int = GIT_TIMEOUT) -> str:
    """Run a git command and return stdout, raising :class:`RepoError` on failure."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - git is always present
        raise RepoError("git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise RepoError(f"git {args[0]} timed out after {timeout}s") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RepoError(scrub(f"git {args[0]} failed: {detail}"))
    return proc.stdout


def repo_dir() -> Path:
    return Path(settings.LOGS_REPO_DIR)


def is_cloned() -> bool:
    return (repo_dir() / ".git").is_dir()


def sync() -> str:
    """Clone the repository if needed, otherwise fast-forward it.

    Returns the commit SHA now checked out.
    """
    target = repo_dir()
    branch = settings.LOGS_REPO_BRANCH

    depth = max(settings.LOGS_CLONE_DEPTH, 0)
    depth_args = ["--depth", str(depth)] if depth else []

    if not is_cloned():
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and any(target.iterdir()):
            raise RepoError(f"{target} exists and is not a git clone")
        run_git(
            [
                "clone",
                "--quiet",
                *depth_args,
                "--branch",
                branch,
                authenticated_url(),
                str(target),
            ]
        )
    else:
        # Refresh the remote URL each time so a rotated token takes effect.
        run_git(["remote", "set-url", "origin", authenticated_url()], cwd=target)
        run_git(["fetch", "--quiet", *depth_args, "origin", branch], cwd=target)
        # The clone is read-only from our side, so a hard reset is always safe
        # and survives force-pushes to the logs repository.
        run_git(["reset", "--hard", "--quiet", f"origin/{branch}"], cwd=target)
        run_git(["clean", "-qfd"], cwd=target)

    # Repeated shallow fetches leave the superseded objects behind. Expiring the
    # reflog is what makes them unreachable so the automatic gc can drop them.
    maintain()

    return head_sha()


def maintain() -> None:
    """Keep the local clone's object store from growing without limit.

    Best effort: a failure here must never stop the dashboard refreshing.
    """
    try:
        run_git(["reflog", "expire", "--expire=now", "--all"], cwd=repo_dir())
        run_git(["gc", "--auto", "--quiet", "--prune=now"], cwd=repo_dir())
    except RepoError as exc:
        logger.warning("git maintenance skipped: %s", exc)


def directory_size(path: Path) -> int:
    """Total size in bytes of every file under ``path``."""
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
        except OSError:  # pragma: no cover - file vanished mid-walk
            continue
    return total


def head_sha() -> str:
    return run_git(["rev-parse", "HEAD"], cwd=repo_dir()).strip()


def remote_sha() -> str:
    """The SHA of the branch tip on the remote, without fetching objects."""
    branch = settings.LOGS_REPO_BRANCH
    out = run_git(["ls-remote", authenticated_url(), f"refs/heads/{branch}"])
    line = out.strip().splitlines()
    if not line:
        raise RepoError(f"remote has no branch {branch}")
    return line[0].split()[0]


def has_remote_changes() -> tuple[bool, str]:
    """Return ``(changed, remote_sha)`` comparing the remote tip with our HEAD."""
    remote = remote_sha()
    if not is_cloned():
        return True, remote
    return remote != head_sha(), remote


def discover_services() -> list[str]:
    """Every top-level folder in the repository that can hold service logs."""
    root = repo_dir()
    if not root.is_dir():
        return []
    names = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name in settings.LOGS_IGNORED_DIRS:
            continue
        names.append(child.name)
    return names


def _timestamp_from_filename(filename: str) -> datetime | None:
    match = FILENAME_TIMESTAMP.search(filename)
    if match:
        try:
            return datetime.strptime(
                match.group(1) + match.group(2), "%Y%m%d%H%M%S"
            ).replace(tzinfo=dt_timezone.utc)
        except ValueError:
            return None
    match = FILENAME_DATE.search(filename)
    if match:
        try:
            return datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                tzinfo=dt_timezone.utc,
            )
        except ValueError:
            return None
    return None


def _commit_info(relative_path: str) -> tuple[str, str, datetime | None]:
    """Latest commit that touched ``relative_path``: ``(sha, subject, when)``."""
    try:
        out = run_git(
            ["log", "-1", "--format=%H%x1f%s%x1f%cI", "--", relative_path],
            cwd=repo_dir(),
        ).strip()
    except RepoError:
        return "", "", None
    if not out:
        return "", "", None
    parts = out.split("\x1f")
    if len(parts) != 3:
        return "", "", None
    sha, subject, iso = parts
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        when = None
    return sha, subject, when


def list_logs(service: str) -> list[LogFile]:
    """All log files for a service, newest first."""
    folder = repo_dir() / service
    if not folder.is_dir():
        return []

    files: list[LogFile] = []
    for child in sorted(folder.iterdir()):
        if not child.is_file() or child.name.startswith("."):
            continue
        if child.suffix.lower() not in settings.LOG_FILE_SUFFIXES:
            continue
        relative = f"{service}/{child.name}"
        stat = child.stat()
        sha, subject, commit_when = _commit_info(relative)
        logged_at = _timestamp_from_filename(child.name) or commit_when
        if logged_at is None:
            logged_at = datetime.fromtimestamp(stat.st_mtime, tz=dt_timezone.utc)
        files.append(
            LogFile(
                service=service,
                path=child,
                relative_path=relative,
                filename=child.name,
                size=stat.st_size,
                logged_at=logged_at,
                commit_sha=sha,
                commit_subject=subject,
            )
        )

    files.sort(key=lambda f: (f.logged_at, f.filename), reverse=True)
    return files


def latest_log(service: str) -> LogFile | None:
    """The single most recent log for a service, which is all the dashboard shows."""
    logs = list_logs(service)
    return logs[0] if logs else None
