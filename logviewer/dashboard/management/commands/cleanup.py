"""``python manage.py cleanup`` - report disk usage and prune what has piled up."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from dashboard.services import cleanup


class Command(BaseCommand):
    help = "Report disk usage for the log viewer and prune prunable files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be pruned without deleting anything.",
        )
        parser.add_argument(
            "--json", action="store_true", help="Emit the report as JSON."
        )

    def handle(self, *args, **options):
        report = cleanup.run(dry_run=options["dry_run"])

        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2))
            return

        labels = {
            "clone_worktree": "logs checkout",
            "clone_git": "git objects",
            "database": "sqlite database",
            "staticfiles": "collected static",
            "claude_transcripts": "claude transcripts",
        }
        before, after = report["before"], report["after"]
        total_before = sum(before.values())
        total_after = sum(after.values())

        self.stdout.write(f"{'':<20}{'before':>10}{'after':>10}")
        for key, label in labels.items():
            self.stdout.write(
                f"{label:<20}{cleanup.human(before[key]):>10}"
                f"{cleanup.human(after[key]):>10}"
            )
        self.stdout.write(
            f"{'total':<20}{cleanup.human(total_before):>10}"
            f"{cleanup.human(total_after):>10}"
        )

        if report["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run: {report['transcripts_prunable']} transcript(s) "
                    "would be deleted."
                )
            )
            return

        freed = total_before - total_after
        self.stdout.write(
            self.style.SUCCESS(
                f"\nRemoved {report['transcripts_removed']} transcript(s), "
                f"freed {cleanup.human(max(freed, 0))}."
            )
        )
