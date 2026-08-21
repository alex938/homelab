import json
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.models import LogSummary, RefreshState, Service, Status
from dashboard.services import refresh as refresh_module
from dashboard.tests.factories import SAMPLE_LOG, add_log, make_repo


def make_service(slug, status=Status.HEALTHY, actions=None, **kwargs):
    service = Service.objects.create(slug=slug, name=slug)
    LogSummary.objects.create(
        service=service,
        log_path=f"{slug}/execute-20260821-090820.log",
        log_filename="execute-20260821-090820.log",
        log_hash=f"hash-{slug}",
        log_bytes=1234,
        commit_sha="a" * 40,
        commit_subject=f"{slug}: run log",
        logged_at=timezone.now(),
        status=status,
        headline=kwargs.get("headline", f"{slug} is {status}"),
        key_points=kwargs.get("key_points", ["first point", "second point"]),
        actions=actions if actions is not None else [],
        summariser=kwargs.get("summariser", "claude"),
    )
    return service


class ViewTestCase(TestCase):
    def setUp(self):
        # Views must never reach the network during tests.
        patcher = mock.patch.object(
            refresh_module, "start_background_refresh", return_value=True
        )
        self.start = patcher.start()
        self.addCleanup(patcher.stop)

        poll_patcher = mock.patch.object(
            refresh_module, "poll_remote_and_refresh_if_needed", return_value=False
        )
        self.poll = poll_patcher.start()
        self.addCleanup(poll_patcher.stop)


class IndexTests(ViewTestCase):
    def test_empty_board_renders_and_kicks_off_a_refresh(self):
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No services yet")
        self.start.assert_called_once()

    def test_a_populated_board_does_not_kick_off_a_refresh(self):
        make_service("seconion")
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 200)
        self.start.assert_not_called()

    def test_cards_show_headline_points_and_actions(self):
        make_service(
            "seconion",
            status=Status.WARNING,
            headline="No active fault found",
            key_points=["Cluster health GREEN"],
            actions=[{"priority": "high", "text": "Run memtest86+ on the host"}],
        )
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "seconion")
        self.assertContains(response, "No active fault found")
        self.assertContains(response, "Cluster health GREEN")
        self.assertContains(response, "Run memtest86+ on the host")
        self.assertContains(response, "execute-20260821-090820.log")

    def test_a_service_with_no_actions_says_so(self):
        make_service("aptcacher", actions=[])
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "no human action needed")

    def test_worst_status_sorts_first(self):
        make_service("aaa-healthy", status=Status.HEALTHY)
        make_service("zzz-critical", status=Status.CRITICAL)
        make_service("mmm-warning", status=Status.WARNING)
        response = self.client.get(reverse("dashboard:index"))
        order = [card["service"].slug for card in response.context["cards"]]
        self.assertEqual(order, ["zzz-critical", "mmm-warning", "aaa-healthy"])

    def test_metrics_count_degraded_services_and_open_actions(self):
        make_service("a", status=Status.HEALTHY, actions=[])
        make_service("b", status=Status.WARNING, actions=[{"priority": "low", "text": "x"}])
        make_service("c", status=Status.CRITICAL, actions=[
            {"priority": "high", "text": "y"}, {"priority": "high", "text": "z"}
        ])
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.context["degraded"], 2)
        self.assertEqual(response.context["open_actions"], 3)

    def test_a_service_awaiting_its_first_summary_still_renders(self):
        Service.objects.create(slug="pending", name="pending")
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Waiting for the first summary")
        self.assertContains(response, "unknown")


class ServiceDetailTests(ViewTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clone = Path(self.tmp.name) / "clone"
        (self.clone / "seconion").mkdir(parents=True)
        (self.clone / "seconion" / "execute-20260821-090820.log").write_text(
            SAMPLE_LOG, encoding="utf-8"
        )
        ctx = override_settings(LOGS_REPO_DIR=self.clone)
        ctx.enable()
        self.addCleanup(ctx.disable)

    def test_detail_shows_the_summary_and_the_raw_log(self):
        make_service("seconion", status=Status.WARNING, actions=[
            {"priority": "high", "text": "Run memtest86+ on the host"}
        ])
        response = self.client.get(
            reverse("dashboard:service_detail", args=["seconion"])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Run memtest86+ on the host")
        self.assertContains(response, "Security Onion Technician Session Log")
        self.assertContains(response, "seconion/execute-20260821-090820.log")

    def test_detail_copes_with_a_missing_local_file(self):
        service = Service.objects.create(slug="gone", name="gone")
        LogSummary.objects.create(
            service=service,
            log_path="gone/missing.log",
            log_filename="missing.log",
            log_hash="h",
            status=Status.UNKNOWN,
            headline="nothing here",
        )
        response = self.client.get(reverse("dashboard:service_detail", args=["gone"]))
        self.assertContains(response, "not present in the local clone")

    def test_detail_for_a_service_with_no_summary(self):
        Service.objects.create(slug="pending", name="pending")
        response = self.client.get(reverse("dashboard:service_detail", args=["pending"]))
        self.assertContains(response, "No summary for this service yet")

    def test_unknown_service_is_a_404(self):
        response = self.client.get(reverse("dashboard:service_detail", args=["nope"]))
        self.assertEqual(response.status_code, 404)


class RefreshEndpointTests(ViewTestCase):
    def test_post_starts_a_refresh_and_redirects(self):
        make_service("seconion")
        response = self.client.post(reverse("dashboard:refresh"))
        self.assertRedirects(response, reverse("dashboard:index"))
        self.start.assert_called_once_with(force=False)

    def test_force_is_passed_through(self):
        self.client.post(reverse("dashboard:refresh"), {"force": "1"})
        self.start.assert_called_once_with(force=True)

    def test_ajax_post_returns_json(self):
        response = self.client.post(
            reverse("dashboard:refresh"), headers={"x-requested-with": "XMLHttpRequest"}
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertTrue(payload["started"])
        self.assertIn("version", payload)

    def test_get_is_rejected(self):
        response = self.client.get(reverse("dashboard:refresh"))
        self.assertEqual(response.status_code, 405)


class StateEndpointTests(ViewTestCase):
    def test_state_reports_the_current_version_and_message(self):
        state = RefreshState.load()
        state.version = 7
        state.message = "Updated seconion"
        state.last_commit_sha = "b" * 40
        state.last_checked_at = timezone.now()
        state.save()
        make_service("seconion")

        response = self.client.get(reverse("dashboard:state"))
        payload = json.loads(response.content)
        self.assertEqual(payload["version"], 7)
        self.assertEqual(payload["message"], "Updated seconion")
        self.assertEqual(payload["commit_sha"], "b" * 8)
        self.assertEqual(payload["services"], 1)
        self.assertFalse(payload["running"])
        self.poll.assert_called_once()

    def test_state_reports_a_running_refresh(self):
        state = RefreshState.load()
        state.running = True
        state.save()
        payload = json.loads(self.client.get(reverse("dashboard:state")).content)
        self.assertTrue(payload["running"])

    def test_state_surfaces_errors(self):
        state = RefreshState.load()
        state.error = "host is down"
        state.save()
        payload = json.loads(self.client.get(reverse("dashboard:state")).content)
        self.assertEqual(payload["error"], "host is down")


class HealthzTests(ViewTestCase):
    def test_healthz(self):
        make_service("seconion")
        payload = json.loads(self.client.get(reverse("dashboard:healthz")).content)
        self.assertEqual(payload, {"ok": True, "services": 1})


class EndToEndTests(TestCase):
    """The whole path: real git repo, stubbed summariser, rendered dashboard."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.origin = make_repo(root / "origin")
        add_log(self.origin, "seconion", "execute-20260821-090820.log", SAMPLE_LOG)

        ctx = override_settings(
            LOGS_REPO_URL=str(self.origin),
            LOGS_REPO_DIR=root / "clone",
            LOGS_REPO_BRANCH="main",
            GITLAB_ACCESS_TOKEN="",
            CLAUDE_COMMAND="definitely-not-a-real-binary",
        )
        ctx.enable()
        self.addCleanup(ctx.disable)
        refresh_module._worker = None
        self.addCleanup(setattr, refresh_module, "_worker", None)

    def test_refresh_then_render_without_a_working_claude_cli(self):
        # With no Claude CLI available the heuristic summariser must carry the board.
        result = refresh_module.run_refresh_and_record()
        self.assertEqual(result.updated, ["seconion"])

        summary = Service.objects.get(slug="seconion").summary
        self.assertEqual(summary.summariser, "heuristic")
        self.assertIn("NO ACTIVE FAULT", summary.headline)
        self.assertTrue(summary.actions)

        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "seconion")
        self.assertContains(response, "HOST-SIDE HARDWARE TESTING")

    def test_a_newly_committed_log_replaces_what_is_displayed(self):
        refresh_module.run_refresh_and_record()
        first = self.client.get(reverse("dashboard:index"))
        self.assertContains(first, "execute-20260821-090820.log")
        version_before = RefreshState.load().version

        add_log(
            self.origin,
            "seconion",
            "execute-20260822-101010.log",
            "OUTCOME: the cluster has failed and the service is DOWN.\n\n"
            "ACTIONS REQUIRED\n\n- Restart the Elasticsearch cluster immediately.\n",
        )
        refresh_module.run_refresh_and_record()

        self.assertEqual(LogSummary.objects.filter(service__slug="seconion").count(), 1)
        self.assertGreater(RefreshState.load().version, version_before)

        second = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(second, "execute-20260821-090820.log")
        self.assertContains(second, "execute-20260822-101010.log")
        self.assertContains(second, "Restart the Elasticsearch cluster")
        self.assertEqual(second.context["cards"][0]["status"], Status.CRITICAL)
