import tempfile
from datetime import timezone as dt_timezone
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from dashboard.services import repo
from dashboard.tests.factories import SAMPLE_LOG, add_log, make_repo


class UrlAndScrubTests(SimpleTestCase):
    @override_settings(
        GITLAB_ACCESS_TOKEN="glpat-secret", LOGS_REPO_URL="https://git.example/x.git"
    )
    def test_token_is_embedded_in_url(self):
        self.assertEqual(
            repo.authenticated_url(),
            "https://oauth2:glpat-secret@git.example/x.git",
        )

    @override_settings(GITLAB_ACCESS_TOKEN="")
    def test_url_is_untouched_without_a_token(self):
        self.assertEqual(
            repo.authenticated_url("https://git.example/x.git"),
            "https://git.example/x.git",
        )

    @override_settings(GITLAB_ACCESS_TOKEN="glpat-secret")
    def test_existing_credentials_are_not_doubled_up(self):
        url = "https://user:pw@git.example/x.git"
        self.assertEqual(repo.authenticated_url(url), url)

    @override_settings(GITLAB_ACCESS_TOKEN="glpat-secret")
    def test_scrub_removes_token_and_url_credentials(self):
        text = "failed for https://oauth2:glpat-secret@git.example/x.git (glpat-secret)"
        scrubbed = repo.scrub(text)
        self.assertNotIn("glpat-secret", scrubbed)
        self.assertIn("***", scrubbed)

    def test_scrub_handles_credentials_it_has_never_seen(self):
        self.assertEqual(
            repo.scrub("https://bob:hunter2@example.com/a.git"),
            "https://***@example.com/a.git",
        )


class RunGitTests(SimpleTestCase):
    def test_failure_raises_repo_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(repo.RepoError):
                repo.run_git(["rev-parse", "HEAD"], cwd=Path(tmp))

    @override_settings(GITLAB_ACCESS_TOKEN="glpat-secret")
    def test_error_text_never_contains_the_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                repo.run_git(["clone", repo.authenticated_url("https://x/y.git"), tmp])
            except repo.RepoError as exc:
                self.assertNotIn("glpat-secret", str(exc))
            else:  # pragma: no cover - the clone must fail
                self.fail("expected RepoError")


class RepoLayoutTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin = make_repo(self.root / "origin")
        add_log(self.origin, "seconion", "execute-20260821-090820.log", SAMPLE_LOG)
        add_log(self.origin, "seconion", "execute-20260820-112519.log", "older\n")
        add_log(self.origin, "aptcacher", "execute-20260820-213202.log", "apt log\n")
        (self.origin / "docs").mkdir()
        (self.origin / "docs" / "notes.md").write_text("x", encoding="utf-8")

        self.clone = self.root / "clone"
        self.settings_ctx = override_settings(
            LOGS_REPO_URL=str(self.origin),
            LOGS_REPO_DIR=self.clone,
            LOGS_REPO_BRANCH="main",
            GITLAB_ACCESS_TOKEN="",
        )
        self.settings_ctx.enable()
        self.addCleanup(self.settings_ctx.disable)

    def test_sync_clones_then_pulls(self):
        self.assertFalse(repo.is_cloned())
        sha = repo.sync()
        self.assertTrue(repo.is_cloned())
        self.assertEqual(len(sha), 40)

        add_log(self.origin, "aptcacher", "execute-20260822-101010.log", "newest\n")
        new_sha = repo.sync()
        self.assertNotEqual(sha, new_sha)
        self.assertTrue((self.clone / "aptcacher" / "execute-20260822-101010.log").is_file())

    def test_sync_discards_local_modifications(self):
        repo.sync()
        target = self.clone / "aptcacher" / "execute-20260820-213202.log"
        target.write_text("tampered\n", encoding="utf-8")
        (self.clone / "aptcacher" / "stray.log").write_text("junk\n", encoding="utf-8")
        repo.sync()
        self.assertEqual(target.read_text(encoding="utf-8"), "apt log\n")
        self.assertFalse((self.clone / "aptcacher" / "stray.log").exists())

    def test_sync_refuses_a_non_empty_non_repo_directory(self):
        self.clone.mkdir(parents=True)
        (self.clone / "something").write_text("x", encoding="utf-8")
        with self.assertRaises(repo.RepoError):
            repo.sync()

    def test_discover_services_skips_dotdirs_and_ignored_names(self):
        repo.sync()
        self.assertEqual(repo.discover_services(), ["aptcacher", "seconion"])

    def test_discover_services_is_empty_before_cloning(self):
        self.assertEqual(repo.discover_services(), [])

    def test_remote_change_detection(self):
        repo.sync()
        changed, remote = repo.has_remote_changes()
        self.assertFalse(changed)
        self.assertEqual(remote, repo.head_sha())

        add_log(self.origin, "seconion", "execute-20260901-000000.log", "newer\n")
        changed, remote = repo.has_remote_changes()
        self.assertTrue(changed)
        self.assertNotEqual(remote, repo.head_sha())

    def test_list_logs_is_newest_first_and_carries_commit_metadata(self):
        repo.sync()
        logs = repo.list_logs("seconion")
        self.assertEqual(
            [log.filename for log in logs],
            ["execute-20260821-090820.log", "execute-20260820-112519.log"],
        )
        newest = logs[0]
        self.assertEqual(newest.relative_path, "seconion/execute-20260821-090820.log")
        self.assertEqual(len(newest.commit_sha), 40)
        self.assertIn("execute-20260821-090820.log", newest.commit_subject)
        self.assertEqual(newest.logged_at.year, 2026)
        self.assertEqual(newest.logged_at.tzinfo, dt_timezone.utc)

    def test_latest_log_reads_content_and_hashes_it(self):
        repo.sync()
        log = repo.latest_log("seconion")
        self.assertEqual(log.read_text(), SAMPLE_LOG)
        self.assertEqual(len(log.content_hash()), 64)
        self.assertEqual(log.size, len(SAMPLE_LOG.encode()))

    def test_latest_log_is_none_for_an_unknown_or_empty_service(self):
        repo.sync()
        self.assertIsNone(repo.latest_log("nope"))
        (self.clone / "empty").mkdir()
        self.assertIsNone(repo.latest_log("empty"))

    def test_non_log_files_are_ignored(self):
        repo.sync()
        (self.clone / "seconion" / "notes.pdf").write_text("x", encoding="utf-8")
        (self.clone / "seconion" / ".gitkeep").write_text("", encoding="utf-8")
        names = [log.filename for log in repo.list_logs("seconion")]
        self.assertNotIn("notes.pdf", names)
        self.assertNotIn(".gitkeep", names)

    def test_untracked_log_falls_back_to_mtime_ordering(self):
        repo.sync()
        untracked = self.clone / "seconion" / "manual.log"
        untracked.write_text("hand written\n", encoding="utf-8")
        logs = repo.list_logs("seconion")
        names = [log.filename for log in logs]
        self.assertIn("manual.log", names)
        manual = next(log for log in logs if log.filename == "manual.log")
        self.assertEqual(manual.commit_sha, "")
        self.assertIsNotNone(manual.logged_at)


class FilenameTimestampTests(SimpleTestCase):
    def test_full_timestamp(self):
        when = repo._timestamp_from_filename("execute-20260821-090820.log")
        self.assertEqual((when.year, when.month, when.day), (2026, 8, 21))
        self.assertEqual((when.hour, when.minute, when.second), (9, 8, 20))

    def test_date_only(self):
        when = repo._timestamp_from_filename("report-2026-08-21.md")
        self.assertEqual((when.year, when.month, when.day), (2026, 8, 21))

    def test_no_timestamp(self):
        self.assertIsNone(repo._timestamp_from_filename("notes.log"))

    def test_impossible_date(self):
        self.assertIsNone(repo._timestamp_from_filename("run-20261345-999999.log"))
