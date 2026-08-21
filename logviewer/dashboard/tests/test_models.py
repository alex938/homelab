from datetime import timedelta

from django.db.utils import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone

from dashboard.models import LogSummary, RefreshState, Service, Status


class ServiceModelTests(TestCase):
    def test_summary_property_returns_the_current_summary(self):
        service = Service.objects.create(slug="seconion", name="seconion")
        self.assertIsNone(service.summary)
        summary = LogSummary.objects.create(
            service=service, log_path="p", log_filename="f", log_hash="h"
        )
        self.assertEqual(service.summary, summary)
        self.assertEqual(str(service), "seconion")

    def test_services_are_ordered_by_slug(self):
        for slug in ("zeta", "alpha", "mid"):
            Service.objects.create(slug=slug, name=slug)
        self.assertEqual(
            list(Service.objects.values_list("slug", flat=True)),
            ["alpha", "mid", "zeta"],
        )

    def test_deleting_a_service_deletes_its_summary(self):
        service = Service.objects.create(slug="s", name="s")
        LogSummary.objects.create(
            service=service, log_path="p", log_filename="f", log_hash="h"
        )
        service.delete()
        self.assertEqual(LogSummary.objects.count(), 0)


class LogSummaryModelTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(slug="seconion", name="seconion")

    def test_defaults(self):
        summary = LogSummary.objects.create(
            service=self.service, log_path="p", log_filename="f.log", log_hash="h"
        )
        self.assertEqual(summary.status, Status.UNKNOWN)
        self.assertEqual(summary.key_points, [])
        self.assertEqual(summary.actions, [])
        self.assertEqual(summary.action_count, 0)
        self.assertFalse(summary.is_degraded)
        self.assertEqual(str(summary), "seconion:f.log")

    def test_action_count_and_degraded_flag(self):
        summary = LogSummary.objects.create(
            service=self.service,
            log_path="p",
            log_filename="f",
            log_hash="h",
            status=Status.WARNING,
            actions=[{"priority": "high", "text": "a"}, {"priority": "low", "text": "b"}],
        )
        self.assertEqual(summary.action_count, 2)
        self.assertTrue(summary.is_degraded)

    def test_a_service_cannot_hold_two_summaries_of_the_same_log(self):
        LogSummary.objects.create(
            service=self.service, log_path="p", log_filename="f", log_hash="dup"
        )
        with self.assertRaises(IntegrityError):
            LogSummary.objects.create(
                service=self.service, log_path="p", log_filename="f", log_hash="dup"
            )

    def test_json_fields_survive_a_round_trip(self):
        actions = [{"priority": "high", "text": "Run memtest86+ on the host"}]
        LogSummary.objects.create(
            service=self.service,
            log_path="p",
            log_filename="f",
            log_hash="h",
            key_points=["one", "two"],
            actions=actions,
        )
        reloaded = LogSummary.objects.get()
        self.assertEqual(reloaded.key_points, ["one", "two"])
        self.assertEqual(reloaded.actions, actions)


class RefreshStateModelTests(TestCase):
    def test_load_is_idempotent_and_stays_a_singleton(self):
        first = RefreshState.load()
        first.version = 3
        first.save()
        second = RefreshState.load()
        self.assertEqual(second.pk, RefreshState.SINGLETON_PK)
        self.assertEqual(second.version, 3)
        self.assertEqual(RefreshState.objects.count(), 1)

    def test_saving_a_new_instance_overwrites_the_singleton_row(self):
        RefreshState.load()
        RefreshState(message="second").save()
        self.assertEqual(RefreshState.objects.count(), 1)
        self.assertEqual(RefreshState.load().message, "second")

    def test_str(self):
        state = RefreshState.load()
        self.assertEqual(str(state), "idle")
        state.running = True
        self.assertEqual(str(state), "running")

    @override_settings(REMOTE_POLL_SECONDS=120)
    def test_is_stale(self):
        state = RefreshState.load()
        self.assertTrue(state.is_stale)

        state.last_checked_at = timezone.now()
        self.assertFalse(state.is_stale)

        state.last_checked_at = timezone.now() - timedelta(seconds=121)
        self.assertTrue(state.is_stale)
