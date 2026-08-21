from django.contrib import admin

from dashboard.models import LogSummary, RefreshState, Service


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "last_seen")
    search_fields = ("slug", "name")


@admin.register(LogSummary)
class LogSummaryAdmin(admin.ModelAdmin):
    list_display = ("service", "log_filename", "status", "summariser", "summarised_at")
    list_filter = ("status", "summariser")
    search_fields = ("service__slug", "log_filename", "headline")


@admin.register(RefreshState)
class RefreshStateAdmin(admin.ModelAdmin):
    list_display = ("running", "version", "last_checked_at", "message")
