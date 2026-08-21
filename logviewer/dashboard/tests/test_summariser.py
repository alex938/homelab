import json
import subprocess
from unittest import mock

from django.test import SimpleTestCase, override_settings

from dashboard.models import Status
from dashboard.services import summariser
from dashboard.tests.factories import SAMPLE_LOG

GOOD_PAYLOAD = {
    "status": "warning",
    "headline": "No active fault, but three human actions remain open.",
    "key_points": ["Cluster health GREEN", "Ingestion real-time"],
    "actions": [
        {"priority": "high", "text": "Run memtest86+ on the KVM host."},
        {"priority": "low", "text": "Decide on elastalert Windows rule tuning."},
    ],
}


def completed(stdout: str, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class ExtractJsonTests(SimpleTestCase):
    def test_plain_json(self):
        self.assertEqual(summariser.extract_json('{"a": 1}'), {"a": 1})

    def test_fenced_json(self):
        raw = 'Sure!\n```json\n{"a": 1}\n```\n'
        self.assertEqual(summariser.extract_json(raw), {"a": 1})

    def test_json_with_surrounding_prose(self):
        raw = 'Here you go: {"a": {"b": 2}} — hope that helps.'
        self.assertEqual(summariser.extract_json(raw), {"a": {"b": 2}})

    def test_no_json_at_all(self):
        with self.assertRaises(summariser.SummariserError):
            summariser.extract_json("I could not read that log.")

    def test_truncated_json(self):
        with self.assertRaises(summariser.SummariserError):
            summariser.extract_json('{"a": 1')

    def test_json_that_is_not_an_object(self):
        with self.assertRaises(summariser.SummariserError):
            summariser.extract_json("[1, 2, 3]")

    def test_malformed_object(self):
        with self.assertRaises(summariser.SummariserError):
            summariser.extract_json("{not json at all}")


class NormaliseTests(SimpleTestCase):
    def test_valid_payload_round_trips(self):
        result = summariser.normalise(GOOD_PAYLOAD)
        self.assertEqual(result.status, "warning")
        self.assertEqual(len(result.key_points), 2)
        self.assertEqual(result.actions[0]["priority"], "high")

    def test_unknown_status_and_priority_are_defaulted(self):
        result = summariser.normalise(
            {"status": "on fire", "actions": [{"priority": "urgent", "text": "do it"}]}
        )
        self.assertEqual(result.status, Status.UNKNOWN)
        self.assertEqual(result.actions[0]["priority"], "medium")

    def test_strings_are_accepted_where_lists_are_expected(self):
        result = summariser.normalise(
            {"key_points": "just one point here", "actions": "just one action here"}
        )
        self.assertEqual(result.key_points, ["just one point here"])
        self.assertEqual(result.actions, [{"priority": "medium", "text": "just one action here"}])

    def test_empty_and_whitespace_entries_are_dropped(self):
        result = summariser.normalise({"key_points": ["", "   ", "kept"], "actions": [""]})
        self.assertEqual(result.key_points, ["kept"])
        self.assertEqual(result.actions, [])

    def test_lists_are_capped_and_text_is_collapsed(self):
        result = summariser.normalise(
            {
                "key_points": [f"point number {i}" for i in range(20)],
                "actions": [{"text": f"action {i}"} for i in range(20)],
                "headline": "line one\n   line two",
            }
        )
        self.assertEqual(len(result.key_points), summariser.MAX_KEY_POINTS)
        self.assertEqual(len(result.actions), summariser.MAX_ACTIONS)
        self.assertEqual(result.headline, "line one line two")

    def test_action_dicts_may_use_an_action_key(self):
        result = summariser.normalise({"actions": [{"action": "restart it"}]})
        self.assertEqual(result.actions[0]["text"], "restart it")

    def test_missing_fields_produce_an_empty_summary(self):
        result = summariser.normalise({})
        self.assertEqual(result.status, Status.UNKNOWN)
        self.assertEqual(result.key_points, [])
        self.assertEqual(result.actions, [])


class BuildPromptTests(SimpleTestCase):
    @override_settings(CLAUDE_MAX_LOG_CHARS=50)
    def test_long_logs_are_truncated(self):
        prompt = summariser.build_prompt("seconion", "a.log", "x" * 500)
        self.assertIn("log truncated", prompt)
        self.assertLess(len(prompt), 2000)

    def test_prompt_names_the_service_and_file(self):
        prompt = summariser.build_prompt("seconion", "execute.log", "body")
        self.assertIn("seconion", prompt)
        self.assertIn("execute.log", prompt)
        self.assertIn("BEGIN LOG", prompt)


@override_settings(CLAUDE_COMMAND="claude -p --dangerously-skip-permissions")
class RunClaudeTests(SimpleTestCase):
    def test_prompt_is_sent_on_stdin_outside_the_project(self):
        with mock.patch("subprocess.run", return_value=completed("{}")) as run:
            summariser.run_claude("hello")
        kwargs = run.call_args.kwargs
        self.assertEqual(run.call_args.args[0][0], "claude")
        self.assertEqual(kwargs["input"], "hello")
        self.assertIn("claude-workdir", kwargs["cwd"])

    def test_missing_binary(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError()):
            with self.assertRaises(summariser.SummariserError):
                summariser.run_claude("hi")

    def test_timeout(self):
        error = subprocess.TimeoutExpired(cmd="claude", timeout=1)
        with mock.patch("subprocess.run", side_effect=error):
            with self.assertRaises(summariser.SummariserError):
                summariser.run_claude("hi")

    def test_non_zero_exit(self):
        with mock.patch("subprocess.run", return_value=completed("", 2, "boom")):
            with self.assertRaises(summariser.SummariserError) as ctx:
                summariser.run_claude("hi")
        self.assertIn("boom", str(ctx.exception))

    def test_empty_output(self):
        with mock.patch("subprocess.run", return_value=completed("   \n")):
            with self.assertRaises(summariser.SummariserError):
                summariser.run_claude("hi")

    @override_settings(CLAUDE_COMMAND="   ")
    def test_empty_command_setting(self):
        with self.assertRaises(summariser.SummariserError):
            summariser.run_claude("hi")


class HeuristicSummaryTests(SimpleTestCase):
    def test_extracts_outcome_points_and_actions(self):
        result = summariser.heuristic_summary("seconion", "a.log", SAMPLE_LOG)
        self.assertEqual(result.summariser, "heuristic")
        self.assertIn("NO ACTIVE FAULT FOUND", result.headline)
        self.assertTrue(result.key_points)
        self.assertTrue(any("HOST-SIDE HARDWARE" in a["text"] for a in result.actions))
        self.assertEqual(len(result.actions), 3)
        self.assertEqual(result.actions[0]["priority"], "high")

    def test_recommendations_heading_is_also_treated_as_actions(self):
        body = (
            "# APT Cacher run\n\n## Overall status: HEALTHY\n\n"
            "- Service up and caching correctly.\n\n"
            "## Recommendations (need a human)\n\n"
            "1. **[MEDIUM] The mounted config is still not being read.**\n"
            "2. **[LOW] No HEALTHCHECK in the image**, so hangs go undetected.\n"
        )
        result = summariser.heuristic_summary("aptcacher", "a.log", body)
        self.assertEqual(len(result.actions), 2)
        self.assertEqual(result.actions[0]["priority"], "medium")
        self.assertEqual(result.actions[1]["priority"], "low")

    def test_status_is_healthy_when_clean_with_no_actions(self):
        body = "Overall status: HEALTHY\n\n- Everything passed.\n- Nothing to report.\n"
        result = summariser.heuristic_summary("x", "a.log", body)
        self.assertEqual(result.status, Status.HEALTHY)

    def test_status_is_warning_when_clean_but_actions_remain(self):
        body = (
            "Overall status: HEALTHY\n\n- All checks passed.\n\n"
            "## Recommendations\n\n1. Please rotate the access token soon.\n"
        )
        result = summariser.heuristic_summary("x", "a.log", body)
        self.assertEqual(result.status, Status.WARNING)

    def test_status_is_critical_on_failure_language(self):
        body = "OUTCOME: service is DOWN, the cluster has failed and is unreachable.\n"
        result = summariser.heuristic_summary("x", "a.log", body)
        self.assertEqual(result.status, Status.CRITICAL)

    def test_empty_log_still_produces_a_headline(self):
        result = summariser.heuristic_summary("x", "a.log", "")
        self.assertIn("a.log", result.headline)
        self.assertEqual(result.actions, [])

    def test_prose_only_log_falls_back_to_leading_lines(self):
        body = (
            "The nightly run completed without any incident worth reporting.\n"
            "Disk utilisation moved from sixty-one percent to sixty-two percent.\n"
            "The upstream mirror answered every request within the usual window.\n"
        )
        result = summariser.heuristic_summary("x", "a.log", body)
        self.assertTrue(result.key_points)


class SummariseTests(SimpleTestCase):
    def test_uses_claude_when_it_returns_valid_json(self):
        payload = json.dumps(GOOD_PAYLOAD)
        with mock.patch.object(summariser, "run_claude", return_value=payload):
            result = summariser.summarise("seconion", "a.log", SAMPLE_LOG)
        self.assertEqual(result.summariser, "claude")
        self.assertEqual(result.status, "warning")
        self.assertEqual(result.error, "")

    def test_falls_back_to_the_heuristic_when_claude_fails(self):
        error = summariser.SummariserError("claude is not installed")
        with mock.patch.object(summariser, "run_claude", side_effect=error):
            result = summariser.summarise("seconion", "a.log", SAMPLE_LOG)
        self.assertEqual(result.summariser, "heuristic")
        self.assertIn("not installed", result.error)
        self.assertTrue(result.actions)

    def test_falls_back_when_claude_returns_prose(self):
        with mock.patch.object(summariser, "run_claude", return_value="I cannot help."):
            result = summariser.summarise("seconion", "a.log", SAMPLE_LOG)
        self.assertEqual(result.summariser, "heuristic")

    def test_falls_back_when_claude_returns_an_empty_summary(self):
        with mock.patch.object(summariser, "run_claude", return_value='{"status":"healthy"}'):
            result = summariser.summarise("seconion", "a.log", SAMPLE_LOG)
        self.assertEqual(result.summariser, "heuristic")
