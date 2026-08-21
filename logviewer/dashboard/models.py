"""Persisted state for the dashboard.

Only one summary is kept per service at any time: the one for that service's
most recent log. When a newer log lands the old summary is deleted, which is
what makes the dashboard "clear and refresh" rather than accumulate history.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class Status(models.TextChoices):
    HEALTHY = "healthy", "Healthy"
    WARNING = "warning", "Warning"
    CRITICAL = "critical", "Critical"
    UNKNOWN = "unknown", "Unknown"


class Service(models.Model):
    """A folder in the logs repository, e.g. ``seconion``."""

    slug = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    first_seen = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.slug

    @property
    def summary(self):
        """The current summary, or ``None`` while one is still being produced."""
        return self.summaries.first()


class LogSummary(models.Model):
    """A summary of one service's most recent log file."""

    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, related_name="summaries"
    )
    log_path = models.CharField(max_length=500)
    log_filename = models.CharField(max_length=300)
    log_hash = models.CharField(max_length=64, db_index=True)
    log_bytes = models.PositiveIntegerField(default=0)
    commit_sha = models.CharField(max_length=64, blank=True)
    commit_subject = models.CharField(max_length=500, blank=True)
    logged_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UNKNOWN
    )
    headline = models.CharField(max_length=500, blank=True)
    key_points = models.JSONField(default=list)
    actions = models.JSONField(default=list)

    summarised_at = models.DateTimeField(default=timezone.now)
    summariser = models.CharField(max_length=50, default="claude")
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-summarised_at"]
        verbose_name_plural = "log summaries"
        constraints = [
            models.UniqueConstraint(
                fields=["service", "log_hash"], name="unique_summary_per_log"
            )
        ]

    def __str__(self) -> str:
        return f"{self.service.slug}:{self.log_filename}"

    @property
    def action_count(self) -> int:
        return len(self.actions or [])

    @property
    def is_degraded(self) -> bool:
        return self.status in {Status.WARNING, Status.CRITICAL}


class RefreshState(models.Model):
    """Singleton row tracking the background refresh worker."""

    SINGLETON_PK = 1

    running = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_commit_sha = models.CharField(max_length=64, blank=True)
    message = models.CharField(max_length=500, blank=True)
    error = models.TextField(blank=True)
    # Bumped whenever the displayed data changes, so the browser knows to reload.
    version = models.PositiveIntegerField(default=0)

    @classmethod
    def load(cls) -> "RefreshState":
        state, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return state

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return "running" if self.running else "idle"

    @property
    def is_stale(self) -> bool:
        """True when the remote has not been polled recently."""
        from django.conf import settings

        if self.last_checked_at is None:
            return True
        age = (timezone.now() - self.last_checked_at).total_seconds()
        return age >= settings.REMOTE_POLL_SECONDS
