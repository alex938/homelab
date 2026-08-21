import os
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from config.env import load_env


class LoadEnvTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / ".env"

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(load_env(Path(self.tmp.name) / "nope.env"), {})

    def test_parses_keys_comments_quotes_and_export(self):
        self.path.write_text(
            "\n".join(
                [
                    "# a comment",
                    "",
                    "GITLAB_ACCESS_TOKEN=glpat-abc123",
                    'QUOTED="with spaces"',
                    "export EXPORTED=yes",
                    "not_a_pair",
                    "WITH_EQUALS=a=b=c",
                ]
            ),
            encoding="utf-8",
        )
        parsed = load_env(self.path)
        self.assertEqual(parsed["GITLAB_ACCESS_TOKEN"], "glpat-abc123")
        self.assertEqual(parsed["QUOTED"], "with spaces")
        self.assertEqual(parsed["EXPORTED"], "yes")
        self.assertEqual(parsed["WITH_EQUALS"], "a=b=c")
        self.assertNotIn("not_a_pair", parsed)
        for key in ("GITLAB_ACCESS_TOKEN", "QUOTED", "EXPORTED", "WITH_EQUALS"):
            self.addCleanup(os.environ.pop, key, None)

    def test_real_environment_wins_over_file(self):
        os.environ["LOGVIEWER_TEST_KEY"] = "from-environment"
        self.addCleanup(os.environ.pop, "LOGVIEWER_TEST_KEY", None)
        self.path.write_text("LOGVIEWER_TEST_KEY=from-file\n", encoding="utf-8")
        parsed = load_env(self.path)
        self.assertEqual(parsed["LOGVIEWER_TEST_KEY"], "from-file")
        self.assertEqual(os.environ["LOGVIEWER_TEST_KEY"], "from-environment")
