"""Dashboard views: one board, one detail page, and two small JSON endpoints."""

from __future__ import annotations

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from dashboard.models import LogSummary, RefreshState, Service, Status
from dashboard.services import refresh as refresh_service
from dashboard.services import repo

STATUS_RANK = {
    Status.CRITICAL: 0,
    Status.WARNING: 1,
    Status.UNKNOWN: 2,
    Status.HEALTHY: 3,
}


def _cards() -> list[dict]:
    """One card per service, worst status first."""
    summaries = {
        summary.service_id: summary
        for summary in LogSummary.objects.select_related("service")
    }
    cards = []
    for service in Service.objects.all():
        summary = summaries.get(service.id)
        cards.append(
            {
                "service": service,
                "summary": summary,
                "status": summary.status if summary else Status.UNKNOWN,
            }
        )
    cards.sort(key=lambda c: (STATUS_RANK.get(c["status"], 2), c["service"].slug))
    return cards


def _state_payload(state: RefreshState) -> dict:
    return {
        "running": state.running or refresh_service.is_refreshing(),
        "version": state.version,
        "message": state.message,
        "error": state.error,
        "commit_sha": state.last_commit_sha[:8],
        "last_checked_at": (
            state.last_checked_at.isoformat() if state.last_checked_at else None
        ),
        "finished_at": state.finished_at.isoformat() if state.finished_at else None,
        "services": Service.objects.count(),
    }


def index(request):
    state = RefreshState.load()
    cards = _cards()

    # First visit with an empty board: start populating it straight away.
    if not cards and not state.running and not refresh_service.is_refreshing():
        refresh_service.start_background_refresh()
        state = RefreshState.load()

    open_actions = sum(len(c["summary"].actions or []) for c in cards if c["summary"])
    return render(
        request,
        "dashboard/index.html",
        {
            "cards": cards,
            "state": state,
            "state_json": _state_payload(state),
            "open_actions": open_actions,
            "degraded": sum(
                1 for c in cards if c["status"] in {Status.WARNING, Status.CRITICAL}
            ),
            "repo_url": settings.LOGS_REPO_URL,
            "poll_seconds": settings.BROWSER_POLL_SECONDS,
        },
    )


def service_detail(request, slug: str):
    service = get_object_or_404(Service, slug=slug)
    summary = service.summary
    raw = ""
    if summary:
        path = repo.repo_dir() / summary.log_path
        if path.is_file():
            raw = path.read_text(encoding="utf-8", errors="replace")
    return render(
        request,
        "dashboard/service_detail.html",
        {
            "service": service,
            "summary": summary,
            "raw_log": raw,
            "raw_lines": raw.count("\n") + 1 if raw else 0,
            "state": RefreshState.load(),
            "poll_seconds": settings.BROWSER_POLL_SECONDS,
        },
    )


@require_POST
def trigger_refresh(request):
    """Manual refresh button. ``force=1`` re-summarises even unchanged logs."""
    force = request.POST.get("force") == "1"
    started = refresh_service.start_background_refresh(force=force)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"started": started, **_state_payload(RefreshState.load())})
    return redirect("dashboard:index")


def state(request):
    """Polled by the browser; also drives automatic pickup of new logs."""
    refresh_service.poll_remote_and_refresh_if_needed()
    return JsonResponse(_state_payload(RefreshState.load()))


def healthz(request):
    return JsonResponse({"ok": True, "services": Service.objects.count()})
