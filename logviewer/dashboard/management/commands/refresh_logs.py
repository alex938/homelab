"""``python manage.py refresh_logs`` - sync and re-summarise from the CLI or cron."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from dashboard.services.refresh import run_refresh_and_record


class Command(BaseCommand):
    help = "Pull the logs repository and summarise each service's newest log."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-summarise every service even if its newest log is unchanged.",
        )
        parser.add_argument(
            "--json", action="store_true", help="Emit the result as JSON."
        )

    def handle(self, *args, **options):
        result = run_refresh_and_record(force=options["force"])

        if options["json"]:
            self.stdout.write(json.dumps(result.as_dict(), indent=2))
        else:
            self.stdout.write(f"commit    : {result.commit_sha[:8]}")
            self.stdout.write(f"services  : {', '.join(result.services) or '-'}")
            self.stdout.write(f"updated   : {', '.join(result.updated) or '-'}")
            self.stdout.write(f"unchanged : {', '.join(result.unchanged) or '-'}")
            if result.removed:
                self.stdout.write(f"removed   : {', '.join(result.removed)}")

        for error in result.errors:
            self.stderr.write(self.style.ERROR(error))
        if result.errors:
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(result.summary_line()))
