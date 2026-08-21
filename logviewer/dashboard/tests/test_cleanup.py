import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from dashboard.services import cleanup, repo, summariser
from dashboard.tests.factories import add_log, make_repo


class TranscriptDirTests(SimpleTestCase):
    def test_directory_is_derived_from_the_work_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DATA_DIR=Path(tmp), CLAUDE_CONFIG_DIR=Path(tmp) / "cfg"):
                expected = (
                    str((Path(tmp) / "claude-workdir").resolve()).replace("/", "-")
                )
                self.assertEqual(summariser.transcript_dir().name, expected)
                self.assertEqual(summariser.transcript_dir().parent.name, "projects")


class PruneTranscriptsTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        ctx = override_settings(
            DATA_DIR=self.root,
            CLAUDE_CONFIG_DIR=self.root / "claude-config",
            CLAUDE_PRUNE_TRANSCRIPTS=True,
            CLAUDE_TRANSCRIPT_KEEP=0,
        )
        ctx.enable()
        self.addCleanup(ctx.disable)

    def write_transcripts(self, count: int) -> Path:
        folder = summariser.transcript_dir()
        folder.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            target = folder / f"session-{index}.jsonl"
            target.write_text("{}\n" * 100, encoding="utf-8")
        return folder

    def test_missing_directory_is_not_an_error(self):
        self.assertEqual(summariser.prune_transcripts(), 0)

    def test_all_transcripts_are_removed_by_default(self):
        folder = self.write_transcripts(3)
        self.assertEqual(summariser.prune_transcripts(), 3)
        self.assertEqual(list(folder.glob("*.jsonl")), [])

    @override_settings(CLAUDE_TRANSCRIPT_KEEP=2)
    def test_the_newest_transcripts_can_be_kept(self):
        folder = self.write_transcripts(5)
        # Make the modification times unambiguous, newest last.
        for index, target in enumerate(sorted(folder.glob("*.jsonl"))):
            import os

            os.utime(target, (1_700_000_000 + index, 1_700_000_000 + index))

        self.assertEqual(summariser.prune_transcripts(), 3)
        remaining = sorted(f.name for f in folder.glob("*.jsonl"))
        self.assertEqual(remaining, ["session-3.jsonl", "session-4.jsonl"])

    @override_settings(CLAUDE_PRUNE_TRANSCRIPTS=False)
    def test_pruning_can_be_disabled(self):
        folder = self.write_transcripts(2)
        self.assertEqual(summariser.prune_transcripts(), 0)
        self.assertEqual(len(list(folder.glob("*.jsonl"))), 2)

    def test_only_transcript_files_are_touched(self):
        folder = self.write_transcripts(1)
        keeper = folder / "notes.txt"
        keeper.write_text("do not delete", encoding="utf-8")
        summariser.prune_transcripts()
        self.assertTrue(keeper.is_file())

    def test_an_undeletable_transcript_is_survivable(self):
        self.write_transcripts(2)
        with mock.patch.object(Path, "unlink", side_effect=OSError("busy")):
            self.assertEqual(summariser.prune_transcripts(), 0)

    def test_run_claude_prunes_even_when_the_cli_fails(self):
        self.write_transcripts(2)
        with override_settings(CLAUDE_COMMAND="definitely-not-a-real-binary"):
            with self.assertRaises(summariser.SummariserError):
                summariser.run_claude("hello")
        self.assertEqual(list(summariser.transcript_dir().glob("*.jsonl")), [])

    def test_run_claude_prunes_after_a_successful_call(self):
        self.write_transcripts(2)
        import subprocess

        done = subprocess.CompletedProcess(["claude"], 0, stdout="{}", stderr="")
        with mock.patch("subprocess.run", return_value=done):
            summariser.run_claude("hello")
        self.assertEqual(list(summariser.transcript_dir().glob("*.jsonl")), [])


class RepoMaintenanceTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin = make_repo(self.root / "origin")
        for index in range(1, 7):
            add_log(
                self.origin, "svc", f"execute-202608{index:02d}-000000.log", f"log {index}\n"
            )

        ctx = override_settings(
            LOGS_REPO_URL=f"file://{self.origin}",
            LOGS_REPO_DIR=self.root / "clone",
            LOGS_REPO_BRANCH="main",
            GITLAB_ACCESS_TOKEN="",
            LOGS_CLONE_DEPTH=2,
        )
        ctx.enable()
        self.addCleanup(ctx.disable)

    def test_the_clone_is_shallow(self):
        repo.sync()
        self.assertTrue((self.root / "clone" / ".git" / "shallow").is_file())
        history = repo.run_git(["rev-list", "--count", "HEAD"], cwd=repo.repo_dir())
        self.assertLessEqual(int(history.strip()), 2)

    def test_the_newest_log_is_still_found_in_a_shallow_clone(self):
        repo.sync()
        log = repo.latest_log("svc")
        self.assertEqual(log.filename, "execute-20260806-000000.log")

    def test_an_older_log_without_commit_metadata_still_sorts(self):
        repo.sync()
        logs = repo.list_logs("svc")
        self.assertEqual(len(logs), 6)
        # Files outside the shallow window have no commit info, but the
        # filename timestamp still orders them correctly.
        self.assertEqual(logs[0].filename, "execute-20260806-000000.log")
        self.assertEqual(logs[-1].filename, "execute-20260801-000000.log")

    @override_settings(LOGS_CLONE_DEPTH=0)
    def test_depth_zero_gives_a_full_clone(self):
        repo.sync()
        self.assertFalse((self.root / "clone" / ".git" / "shallow").is_file())

    def test_repeated_syncs_do_not_grow_the_object_store(self):
        repo.sync()
        first = repo.directory_size(repo.repo_dir() / ".git")
        for index in range(7, 13):
            add_log(
                self.origin, "svc", f"execute-202608{index:02d}-000000.log", f"log {index}\n"
            )
            repo.sync()
        final = repo.directory_size(repo.repo_dir() / ".git")
        # Six more commits must not multiply the object store.
        self.assertLess(final, first * 3)

    def test_maintenance_failure_is_swallowed(self):
        repo.sync()
        with mock.patch.object(repo, "run_git", side_effect=repo.RepoError("locked")):
            repo.maintain()  # must not raise

    def test_directory_size(self):
        target = self.root / "sizes"
        (target / "nested").mkdir(parents=True)
        (target / "a.txt").write_text("x" * 100, encoding="utf-8")
        (target / "nested" / "b.txt").write_text("y" * 50, encoding="utf-8")
        self.assertEqual(repo.directory_size(target), 150)
        self.assertEqual(repo.directory_size(target / "a.txt"), 100)
        self.assertEqual(repo.directory_size(self.root / "missing"), 0)


class CleanupReportTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin = make_repo(self.root / "origin")
        add_log(self.origin, "svc", "execute-20260821-090820.log", "body\n")

        ctx = override_settings(
            LOGS_REPO_URL=str(self.origin),
            LOGS_REPO_DIR=self.root / "clone",
            LOGS_REPO_BRANCH="main",
            GITLAB_ACCESS_TOKEN="",
            DATA_DIR=self.root,
            CLAUDE_CONFIG_DIR=self.root / "claude-config",
            CLAUDE_PRUNE_TRANSCRIPTS=True,
            CLAUDE_TRANSCRIPT_KEEP=0,
        )
        ctx.enable()
        self.addCleanup(ctx.disable)

    def seed_transcripts(self, count=3):
        folder = summariser.transcript_dir()
        folder.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            (folder / f"s{index}.jsonl").write_text("x" * 1024, encoding="utf-8")

    def test_human_readable_sizes(self):
        self.assertEqual(cleanup.human(512), "512B")
        self.assertEqual(cleanup.human(2048), "2.0KB")
        self.assertEqual(cleanup.human(5 * 1024 * 1024), "5.0MB")

    def test_usage_reports_every_growth_area(self):
        repo.sync()
        self.seed_transcripts(2)
        usage = cleanup.usage()
        self.assertEqual(
            sorted(usage),
            [
                "claude_transcripts",
                "clone_git",
                "clone_worktree",
                "database",
                "staticfiles",
            ],
        )
        self.assertGreater(usage["clone_git"], 0)
        self.assertGreater(usage["claude_transcripts"], 0)

    def test_run_frees_transcripts(self):
        repo.sync()
        self.seed_transcripts(3)
        report = cleanup.run()
        self.assertEqual(report["transcripts_removed"], 3)
        self.assertEqual(report["after"]["claude_transcripts"], 0)
        self.assertFalse(report["dry_run"])

    def test_dry_run_deletes_nothing(self):
        self.seed_transcripts(3)
        report = cleanup.run(dry_run=True)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["transcripts_removed"], 0)
        self.assertEqual(report["transcripts_prunable"], 3)
        self.assertEqual(cleanup.transcript_count(), 3)

    def test_run_works_before_the_repository_is_cloned(self):
        self.seed_transcripts(1)
        report = cleanup.run()
        self.assertEqual(report["transcripts_removed"], 1)

    def test_command_prints_a_table(self):
        repo.sync()
        self.seed_transcripts(2)
        out = StringIO()
        call_command("cleanup", stdout=out)
        printed = out.getvalue()
        self.assertIn("claude transcripts", printed)
        self.assertIn("git objects", printed)
        self.assertIn("Removed 2 transcript(s)", printed)

    def test_command_dry_run(self):
        self.seed_transcripts(2)
        out = StringIO()
        call_command("cleanup", "--dry-run", stdout=out)
        self.assertIn("2 transcript(s) would be deleted", out.getvalue())
        self.assertEqual(cleanup.transcript_count(), 2)

    def test_command_json(self):
        import json

        self.seed_transcripts(1)
        out = StringIO()
        call_command("cleanup", "--json", stdout=out)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["transcripts_removed"], 1)
