"""Turn a raw agent log into the short summary the dashboard displays.

The primary summariser shells out to the Claude CLI (``claude -p
--dangerously-skip-permissions``) and asks for strict JSON. If the CLI is
missing, times out, or returns something unparseable, a deterministic
heuristic summariser takes over so the dashboard always shows something.
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from dashboard.models import Status

logger = logging.getLogger(__name__)

MAX_KEY_POINTS = 6
MAX_ACTIONS = 6
VALID_STATUSES = {s.value for s in Status}
VALID_PRIORITIES = {"high", "medium", "low", "info"}

PROMPT_TEMPLATE = """\
You are summarising a homelab agent's log file for an operations dashboard.
The dashboard shows one short card per service, so be brief and concrete.

Service: {service}
Log file: {filename}

Respond with ONE JSON object and nothing else. No prose, no code fences.
Schema:
{{
  "status": "healthy" | "warning" | "critical" | "unknown",
  "headline": "one sentence, max 140 characters, stating the overall outcome",
  "key_points": ["3-6 short findings, max 140 characters each"],
  "actions": [
    {{"priority": "high"|"medium"|"low"|"info",
      "text": "an action the human operator must take, max 160 characters"}}
  ]
}}

Rules:
- "status" reflects the service, not the log: healthy if nothing is wrong,
  warning if there are open issues that are not yet hurting the service,
  critical if the service is failing or degraded right now.
- "actions" lists only things a human must do. Use an empty list if the log
  says no human action is needed. Do not invent actions.
- Prefer the log's own wording for findings. Do not speculate.
- Never include secrets, tokens, passwords or IP credentials.

--- BEGIN LOG ---
{body}
--- END LOG ---
"""


@dataclass
class Summary:
    """The normalised result of summarising one log."""

    status: str = Status.UNKNOWN
    headline: str = ""
    key_points: list[str] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    summariser: str = "claude"
    error: str = ""


class SummariserError(RuntimeError):
    """The Claude CLI could not produce a summary."""


def _clean(text: object, limit: int) -> str:
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def extract_json(raw: str) -> dict:
    """Pull the first JSON object out of CLI output that may have extra text."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start == -1:
            raise SummariserError("no JSON object in summariser output")
        depth = 0
        end = -1
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end == -1:
            raise SummariserError("truncated JSON in summariser output")
        try:
            parsed = json.loads(text[start:end])
        except json.JSONDecodeError as exc:
            raise SummariserError(f"invalid JSON from summariser: {exc}") from exc

    if not isinstance(parsed, dict):
        raise SummariserError("summariser returned JSON that is not an object")
    return parsed


def normalise(payload: dict, summariser: str = "claude") -> Summary:
    """Coerce whatever the model returned into the shape the templates expect."""
    status = str(payload.get("status", "")).strip().lower()
    if status not in VALID_STATUSES:
        status = Status.UNKNOWN

    points = payload.get("key_points") or []
    if isinstance(points, str):
        points = [points]
    key_points = [
        cleaned
        for cleaned in (_clean(p, 200) for p in list(points)[:MAX_KEY_POINTS])
        if cleaned
    ]

    raw_actions = payload.get("actions") or []
    if isinstance(raw_actions, str):
        raw_actions = [raw_actions]
    actions: list[dict] = []
    for item in list(raw_actions)[:MAX_ACTIONS]:
        if isinstance(item, dict):
            text = _clean(item.get("text") or item.get("action"), 240)
            priority = str(item.get("priority", "medium")).strip().lower()
        else:
            text = _clean(item, 240)
            priority = "medium"
        if not text:
            continue
        if priority not in VALID_PRIORITIES:
            priority = "medium"
        actions.append({"priority": priority, "text": text})

    return Summary(
        status=status,
        headline=_clean(payload.get("headline"), 400),
        key_points=key_points,
        actions=actions,
        summariser=summariser,
    )


def build_prompt(service: str, filename: str, body: str) -> str:
    limit = settings.CLAUDE_MAX_LOG_CHARS
    if len(body) > limit:
        body = body[:limit] + "\n[... log truncated for summarisation ...]"
    return PROMPT_TEMPLATE.format(service=service, filename=filename, body=body)


def _workdir() -> Path:
    """An empty directory to run the CLI in.

    The CLI must not run inside this project, or it would pick up the project's
    own CLAUDE.md and answer as the log-viewer technician instead of returning
    the JSON we asked for.
    """
    path = Path(settings.DATA_DIR) / "claude-workdir"
    path.mkdir(parents=True, exist_ok=True)
    return path


def transcript_dir() -> Path:
    """Where the Claude CLI stores session transcripts for our work directory.

    The CLI derives this directory from the working directory by replacing every
    path separator with a dash. We only ever touch the directory belonging to our
    own private work directory, never any other project's.
    """
    encoded = str(_workdir().resolve()).replace("/", "-")
    return Path(settings.CLAUDE_CONFIG_DIR) / "projects" / encoded


def prune_transcripts() -> int:
    """Delete the CLI's session transcripts for our work directory.

    Each summarisation writes one transcript containing the whole log that was
    piped in. They live outside this project and nothing else would ever clean
    them up, so they are removed here. Returns the number of files deleted.
    """
    if not settings.CLAUDE_PRUNE_TRANSCRIPTS:
        return 0

    folder = transcript_dir()
    if not folder.is_dir():
        return 0

    try:
        files = sorted(
            (f for f in folder.glob("*.jsonl") if f.is_file()),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
    except OSError as exc:  # pragma: no cover - unreadable directory
        logger.warning("could not list transcripts in %s: %s", folder, exc)
        return 0

    keep = max(settings.CLAUDE_TRANSCRIPT_KEEP, 0)
    removed = 0
    for stale in files[keep:]:
        try:
            stale.unlink()
            removed += 1
        except OSError as exc:  # pragma: no cover - racing another process
            logger.warning("could not delete transcript %s: %s", stale, exc)

    if removed:
        logger.info("pruned %s Claude transcript(s) from %s", removed, folder)
    return removed


def run_claude(prompt: str) -> str:
    """Invoke the configured Claude CLI with the prompt on stdin.

    The CLI's session transcript is pruned afterwards whether or not the call
    succeeded, so a failing summariser cannot quietly fill the disk either.
    """
    command = shlex.split(settings.CLAUDE_COMMAND)
    if not command:
        raise SummariserError("CLAUDE_COMMAND is empty")
    try:
        proc = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=settings.CLAUDE_TIMEOUT_SECONDS,
            cwd=str(_workdir()),
            check=False,
        )
    except FileNotFoundError as exc:
        raise SummariserError(f"{command[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise SummariserError(
            f"summariser timed out after {settings.CLAUDE_TIMEOUT_SECONDS}s"
        ) from exc
    finally:
        prune_transcripts()

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:500]
        raise SummariserError(f"summariser exited {proc.returncode}: {detail}")
    if not proc.stdout.strip():
        raise SummariserError("summariser returned no output")
    return proc.stdout


# --- Heuristic fallback -------------------------------------------------------

ACTION_HEADINGS = re.compile(
    r"^\s*#*\s*(actions? required.*|recommendations?.*|action items?.*|"
    r"next steps.*|open items?.*|todo.*)$",
    re.IGNORECASE,
)
SECTION_BREAK = re.compile(r"^(={5,}|-{5,}|#{1,6}\s|\*{3,})")
BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)]|[a-z][.)])\s+(.*)$")
PRIORITY_HINT = re.compile(
    r"(\bpriority\s*1\b|\[high\]|\bcritical\b|\burgent\b)|"
    r"(\bpriority\s*2\b|\[medium\])|"
    r"(\bpriority\s*3\b|\[low\]|\[info\])",
    re.IGNORECASE,
)
CRITICAL_WORDS = re.compile(
    r"\b(critical|fatal|outage|down|failed|failure|corrupt|red\b|unreachable)\b",
    re.IGNORECASE,
)
WARNING_WORDS = re.compile(
    r"\b(warning|warn|degraded|known fault|open item|segfault|error|yellow\b|stale)\b",
    re.IGNORECASE,
)
HEALTHY_WORDS = re.compile(
    r"\b(healthy|all green|green\b|no active fault|pass\b|ok\b|nominal|success)\b",
    re.IGNORECASE,
)


def _priority_for(line: str) -> str:
    match = PRIORITY_HINT.search(line)
    if not match:
        return "medium"
    if match.group(1):
        return "high"
    if match.group(2):
        return "medium"
    return "low"


def heuristic_summary(service: str, filename: str, body: str) -> Summary:
    """A no-model fallback: scrape headline, findings and action sections."""
    lines = body.splitlines()

    headline = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or SECTION_BREAK.match(stripped):
            continue
        if re.match(r"^(outcome|overall status|status|result)\b", stripped, re.I):
            headline = stripped
            break
        if not headline:
            headline = stripped
    headline = _clean(headline.lstrip("# "), 400)

    # Actions: everything under an "actions required" style heading.
    actions: list[dict] = []
    in_actions = False
    for line in lines:
        stripped = line.strip().strip("=").strip()
        if ACTION_HEADINGS.match(stripped):
            in_actions = True
            continue
        if not in_actions:
            continue
        if not stripped:
            continue
        if SECTION_BREAK.match(line.strip()) and not BULLET.match(line):
            if len(actions) >= 1:
                in_actions = False
            continue
        bullet = BULLET.match(line)
        candidate = bullet.group(1) if bullet else stripped
        candidate = _clean(re.sub(r"\*\*", "", candidate), 240)
        if len(candidate) < 12:
            continue
        actions.append({"priority": _priority_for(candidate), "text": candidate})
        if len(actions) >= MAX_ACTIONS:
            break

    # Key points: the most informative bullet/table lines in the log.
    key_points: list[str] = []
    for line in lines:
        bullet = BULLET.match(line)
        if not bullet:
            continue
        candidate = _clean(re.sub(r"\*\*|`", "", bullet.group(1)), 200)
        if len(candidate) < 15 or candidate in key_points:
            continue
        if any(candidate == action["text"] for action in actions):
            continue
        key_points.append(candidate)
        if len(key_points) >= MAX_KEY_POINTS:
            break

    if not key_points:
        for line in lines:
            candidate = _clean(line, 200)
            if len(candidate) < 25 or SECTION_BREAK.match(line.strip()):
                continue
            if candidate == headline or candidate in key_points:
                continue
            key_points.append(candidate)
            if len(key_points) >= 3:
                break

    head = "\n".join(lines[:80])
    if CRITICAL_WORDS.search(head) and not HEALTHY_WORDS.search(head):
        status = Status.CRITICAL
    elif HEALTHY_WORDS.search(head):
        status = Status.WARNING if actions else Status.HEALTHY
    elif WARNING_WORDS.search(head):
        status = Status.WARNING
    else:
        status = Status.UNKNOWN

    return Summary(
        status=status,
        headline=headline or f"Latest log for {service}: {filename}",
        key_points=key_points,
        actions=actions,
        summariser="heuristic",
    )


def summarise(service: str, filename: str, body: str) -> Summary:
    """Summarise a log, falling back to the heuristic summariser on any failure."""
    prompt = build_prompt(service, filename, body)
    try:
        raw = run_claude(prompt)
        summary = normalise(extract_json(raw), summariser="claude")
        if not summary.headline and not summary.key_points:
            raise SummariserError("summariser returned an empty summary")
        return summary
    except SummariserError as exc:
        logger.warning("claude summariser failed for %s: %s", service, exc)
        fallback = heuristic_summary(service, filename, body)
        fallback.error = str(exc)
        return fallback
