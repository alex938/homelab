import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from dashboard.models import LogSummary, RefreshState, Service, Status
from dashboard.services import refresh as refresh_module
from dashboard.services import repo, summariser
from dashboard.tests.factories import SAMPLE_LOG, add_log, make_repo


def fake_summary(status=Status.WARNING, headline="fake headline", **kwargs):
    return summariser.Summary(
        status=status,
        headline=headline,
        key_points=kwargs.get("key_points", ["point one"]),
        actions=kwargs.get("actions", [{"priority": "high", "text": "do the thing"}]),
        summariser=kwargs.get("summariser", "claude"),
    )


class RefreshTestCase(TestCase):
    """Shared fixture: an origin repo, a clone path, and a stubbed summariser."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin = make_repo(self.root / "origin")
        add_log(self.origin, "seconion", "execute-20260821-090820.log", SAMPLE_LOG)
        add_log(self.origin, "aptcacher", "execute-20260820-213202.log", "apt log body\n")

        ctx = override_settings(
            LOGS_REPO_URL=str(self.origin),
            LOGS_REPO_DIR=self.root / "clone",
            LOGS_REPO_BRANCH="main",
            GITLAB_ACCESS_TOKEN="",
            REMOTE_POLL_SECONDS=120,
        )
        ctx.enable()
        self.addCleanup(ctx.disable)

        patcher = mock.patch.object(
            summariser, "summarise", side_effect=lambda *a, **k: fake_summary()
        )
        self.summarise = patcher.start()
        self.addCleanup(patcher.stop)

        refresh_module._worker = None
        self.addCleanup(setattr, refresh_module, "_worker", None)


class RefreshTests(RefreshTestCase):
    def test_first_run_creates_one_summary_per_service(self):
        result = refresh_module.refresh()
        self.assertEqual(result.services, ["aptcacher", "seconion"])
        self.assertEqual(sorted(result.updated), ["aptcacher", "seconion"])
        self.assertEqual(Service.objects.count(), 2)
        self.assertEqual(LogSummary.objects.count(), 2)
        self.assertEqual(self.summarise.call_count, 2)

        summary = Service.objects.get(slug="seconion").summary
        self.assertEqual(summary.log_filename, "execute-20260821-090820.log")
        self.assertEqual(summary.status, Status.WARNING)
        self.assertEqual(summary.actions[0]["priority"], "high")

    def test_only_the_newest_log_is_summarised(self):
        add_log(self.origin, "seconion", "execute-20260101-000000.log", "ancient\n")
        refresh_module.refresh()
        summaries = LogSummary.objects.filter(service__slug="seconion")
        self.assertEqual(summaries.count(), 1)
        self.assertEqual(summaries.first().log_filename, "execute-20260821-090820.log")

    def test_second_run_without_changes_does_not_re_summarise(self):
        refresh_module.refresh()
        self.summarise.reset_mock()
        result = refresh_module.refresh()
        self.assertEqual(sorted(result.unchanged), ["aptcacher", "seconion"])
        self.assertEqual(result.updated, [])
        self.summarise.assert_not_called()
        self.assertFalse(result.changed)

    def test_force_re_summarises_unchanged_logs(self):
        refresh_module.refresh()
        self.summarise.reset_mock()
        result = refresh_module.refresh(force=True)
        self.assertEqual(sorted(result.updated), ["aptcacher", "seconion"])
        self.assertEqual(self.summarise.call_count, 2)

    def test_a_new_log_replaces_the_old_summary(self):
        refresh_module.refresh()
        old = Service.objects.get(slug="seconion").summary
        self.summarise.side_effect = lambda *a, **k: fake_summary(
            status=Status.CRITICAL, headline="everything is on fire"
        )

        add_log(self.origin, "seconion", "execute-20260822-101010.log", "brand new\n")
        result = refresh_module.refresh()

        self.assertEqual(result.updated, ["seconion"])
        self.assertEqual(LogSummary.objects.filter(service__slug="seconion").count(), 1)
        self.assertFalse(LogSummary.objects.filter(pk=old.pk).exists())
        new = Service.objects.get(slug="seconion").summary
        self.assertEqual(new.log_filename, "execute-20260822-101010.log")
        self.assertEqual(new.headline, "everything is on fire")
        self.assertEqual(new.status, Status.CRITICAL)

    def test_an_edited_log_with_the_same_name_is_re_summarised(self):
        refresh_module.refresh()
        self.summarise.reset_mock()
        add_log(
            self.origin, "aptcacher", "execute-20260820-213202.log", "apt log body v2\n"
        )
        result = refresh_module.refresh()
        self.assertEqual(result.updated, ["aptcacher"])
        self.assertEqual(self.summarise.call_count, 1)

    def test_a_new_service_folder_is_picked_up(self):
        refresh_module.refresh()
        add_log(self.origin, "pihole", "execute-20260822-090000.log", "pihole log\n")
        result = refresh_module.refresh()
        self.assertIn("pihole", result.services)
        self.assertIn("pihole", result.updated)
        self.assertTrue(Service.objects.filter(slug="pihole").exists())

    def test_a_removed_service_folder_drops_off_the_board(self):
        refresh_module.refresh()
        Service.objects.create(slug="ghost", name="ghost")
        result = refresh_module.refresh()
        self.assertEqual(result.removed, ["ghost"])
        self.assertFalse(Service.objects.filter(slug="ghost").exists())

    def test_a_service_folder_emptied_of_logs_loses_its_summary(self):
        refresh_module.refresh()
        empty = self.root / "clone" / "newthing"
        empty.mkdir()
        updated, note = refresh_module.refresh_service("newthing")
        self.assertFalse(updated)
        self.assertEqual(note, "no logs in folder")
        self.assertTrue(Service.objects.filter(slug="newthing").exists())
        self.assertFalse(LogSummary.objects.filter(service__slug="newthing").exists())

    def test_one_broken_service_does_not_stop_the_others(self):
        real = refresh_module.refresh_service

        def explode(name, force=False):
            if name == "seconion":
                raise RuntimeError("kaboom")
            return real(name, force=force)

        with mock.patch.object(refresh_module, "refresh_service", side_effect=explode):
            result = refresh_module.refresh()

        self.assertEqual(result.updated, ["aptcacher"])
        self.assertEqual(len(result.errors), 1)
        self.assertIn("kaboom", result.errors[0])


class RefreshStateTests(RefreshTestCase):
    def test_state_is_recorded_and_version_bumps_on_change(self):
        result = refresh_module.run_refresh_and_record()
        state = RefreshState.load()
        self.assertFalse(state.running)
        self.assertEqual(state.version, 1)
        self.assertEqual(state.last_commit_sha, result.commit_sha)
        self.assertIsNotNone(state.finished_at)
        self.assertEqual(state.error, "")

    def test_version_does_not_bump_when_nothing_changed(self):
        refresh_module.run_refresh_and_record()
        refresh_module.run_refresh_and_record()
        self.assertEqual(RefreshState.load().version, 1)

    def test_version_bumps_again_when_a_new_log_lands(self):
        refresh_module.run_refresh_and_record()
        add_log(self.origin, "seconion", "execute-20260822-101010.log", "new\n")
        refresh_module.run_refresh_and_record()
        self.assertEqual(RefreshState.load().version, 2)

    def test_a_sync_failure_is_recorded_not_raised(self):
        with mock.patch.object(repo, "sync", side_effect=repo.RepoError("no network")):
            result = refresh_module.run_refresh_and_record()
        state = RefreshState.load()
        self.assertFalse(state.running)
        self.assertIn("no network", state.error)
        self.assertEqual(state.message, "Refresh failed")
        self.assertEqual(result.errors, ["no network"])

    @override_settings(GITLAB_ACCESS_TOKEN="glpat-secret")
    def test_a_failure_never_records_the_token(self):
        boom = repo.RepoError("clone of https://oauth2:glpat-secret@h/x.git failed")
        with mock.patch.object(repo, "sync", side_effect=boom):
            refresh_module.run_refresh_and_record()
        self.assertNotIn("glpat-secret", RefreshState.load().error)

    def test_singleton_state_never_creates_a_second_row(self):
        RefreshState.load().save()
        refresh_module.run_refresh_and_record()
        self.assertEqual(RefreshState.objects.count(), 1)


class PollRemoteTests(RefreshTestCase):
    def test_a_fresh_check_is_skipped(self):
        state = RefreshState.load()
        state.last_checked_at = timezone.now()
        state.save()
        with mock.patch.object(repo, "has_remote_changes") as check:
            self.assertFalse(refresh_module.poll_remote_and_refresh_if_needed())
        check.assert_not_called()

    def test_a_stale_check_with_no_remote_changes_does_nothing(self):
        refresh_module.run_refresh_and_record()
        state = RefreshState.load()
        state.last_checked_at = None
        state.save()
        with mock.patch.object(refresh_module, "start_background_refresh") as start:
            started = refresh_module.poll_remote_and_refresh_if_needed()
        self.assertFalse(started)
        start.assert_not_called()
        self.assertIsNotNone(RefreshState.load().last_checked_at)

    def test_a_new_remote_commit_starts_a_refresh(self):
        refresh_module.run_refresh_and_record()
        state = RefreshState.load()
        state.last_checked_at = None
        state.save()
        add_log(self.origin, "seconion", "execute-20260822-101010.log", "new\n")
        with mock.patch.object(
            refresh_module, "start_background_refresh", return_value=True
        ) as start:
            self.assertTrue(refresh_module.poll_remote_and_refresh_if_needed())
        start.assert_called_once()

    def test_an_empty_board_always_triggers_a_refresh(self):
        with mock.patch.object(
            refresh_module, "start_background_refresh", return_value=True
        ) as start:
            self.assertTrue(refresh_module.poll_remote_and_refresh_if_needed())
        start.assert_called_once()

    def test_a_running_refresh_is_not_disturbed(self):
        state = RefreshState.load()
        state.running = True
        state.save()
        with mock.patch.object(repo, "has_remote_changes") as check:
            self.assertFalse(refresh_module.poll_remote_and_refresh_if_needed())
        check.assert_not_called()

    def test_an_unreachable_remote_is_recorded_and_swallowed(self):
        with mock.patch.object(
            repo, "has_remote_changes", side_effect=repo.RepoError("host is down")
        ):
            self.assertFalse(refresh_module.poll_remote_and_refresh_if_needed())
        state = RefreshState.load()
        self.assertIn("host is down", state.error)
        self.assertIsNotNone(state.last_checked_at)


class BackgroundRefreshTests(RefreshTestCase):
    """The worker is exercised without a real thread.

    A live thread would use its own database connection, which SQLite's
    in-memory test database cannot share safely, so the thread body and the
    thread launcher are tested separately.
    """

    def test_start_launches_a_daemon_thread(self):
        with mock.patch.object(refresh_module.threading, "Thread") as Thread:
            self.assertTrue(refresh_module.start_background_refresh(force=True))
        Thread.assert_called_once()
        self.assertEqual(Thread.call_args.kwargs["args"], (True,))
        self.assertTrue(Thread.call_args.kwargs["daemon"])
        Thread.return_value.start.assert_called_once()

    def test_a_second_start_is_refused_while_one_is_running(self):
        thread = mock.Mock()
        thread.is_alive.return_value = True
        with mock.patch.object(refresh_module, "_worker", thread):
            self.assertFalse(refresh_module.start_background_refresh())
            self.assertTrue(refresh_module.is_refreshing())

    def test_a_finished_worker_does_not_block_the_next_start(self):
        thread = mock.Mock()
        thread.is_alive.return_value = False
        with mock.patch.object(refresh_module, "_worker", thread):
            self.assertFalse(refresh_module.is_refreshing())
            with mock.patch.object(refresh_module.threading, "Thread"):
                self.assertTrue(refresh_module.start_background_refresh())

    def test_the_worker_body_runs_a_refresh_and_closes_connections(self):
        with mock.patch.object(refresh_module, "close_old_connections") as close:
            refresh_module._worker_body(force=False)
        self.assertEqual(Service.objects.count(), 2)
        self.assertEqual(close.call_count, 2)

    def test_the_worker_body_closes_connections_even_when_the_refresh_blows_up(self):
        with mock.patch.object(
            refresh_module, "run_refresh_and_record", side_effect=RuntimeError("boom")
        ):
            with mock.patch.object(refresh_module, "close_old_connections") as close:
                with self.assertRaises(RuntimeError):
                    refresh_module._worker_body(force=False)
        self.assertEqual(close.call_count, 2)


class ManagementCommandTests(RefreshTestCase):
    def test_command_refreshes_and_reports(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("refresh_logs", stdout=out)
        printed = out.getvalue()
        self.assertIn("aptcacher", printed)
        self.assertIn("seconion", printed)
        self.assertEqual(LogSummary.objects.count(), 2)

    def test_command_json_output(self):
        import json
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("refresh_logs", "--json", stdout=out)
        payload = json.loads(out.getvalue().split("Updated")[0].strip())
        self.assertEqual(payload["services"], ["aptcacher", "seconion"])

    def test_command_exits_non_zero_on_error(self):
        from io import StringIO

        from django.core.management import call_command

        with mock.patch.object(repo, "sync", side_effect=repo.RepoError("nope")):
            with self.assertRaises(SystemExit):
                call_command("refresh_logs", stdout=StringIO(), stderr=StringIO())
