import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import _common
import post_tool


def get_failure_payload(tool_name="Read", tool_input=None, error="File does not exist."):
    payload = {
        "session_id": "session-a",
        "hook_event_name": "PostToolUseFailure",
        "tool_name": tool_name,
        "tool_input": tool_input or {"file_path": "/example/missing.txt"},
        "tool_use_id": "toolu_example_1",
    }
    if error is not None:
        payload["error"] = error
    return payload


def get_stdin_with_payload(payload):
    payload_bytes = json.dumps(payload).encode("utf-8")
    return io.TextIOWrapper(io.BytesIO(payload_bytes), encoding="utf-8")


def read_events_written_by_main(payload):
    with tempfile.TemporaryDirectory() as events_dir:
        events_path = Path(events_dir)
        with mock.patch.object(_common, "EVENTS_DIR", events_path):
            with mock.patch.object(sys, "stdin", get_stdin_with_payload(payload)):
                post_tool.main()
        events_file = events_path / f"{payload['session_id']}.jsonl"
        lines = events_file.read_text(encoding="utf-8").splitlines()
    events = []
    for line in lines:
        events.append(json.loads(line))
    return events


class FailurePayload(unittest.TestCase):
    def test_failure_event_name_alone_marks_the_post_tool_event_as_error(self):
        payload = get_failure_payload(error=None)

        event = post_tool.build_event(payload)

        self.assertEqual(event["phase"], "post_tool")
        self.assertEqual(event["is_error"], True)

    def test_failure_error_message_equals_payload_error(self):
        payload = get_failure_payload(error="File does not exist.")

        event = post_tool.build_event(payload)

        self.assertEqual(event["error_message"], "File does not exist.")

    def test_failure_error_message_is_cut_to_500_characters(self):
        payload = get_failure_payload(error="x" * 600)

        event = post_tool.build_event(payload)

        self.assertEqual(event["error_message"], "x" * 500)

    def test_failure_error_message_is_null_when_error_is_missing(self):
        payload = get_failure_payload(error=None)

        event = post_tool.build_event(payload)

        self.assertIsNone(event["error_message"])

    def test_failure_error_message_is_null_when_error_is_empty(self):
        payload = get_failure_payload(error="")

        event = post_tool.build_event(payload)

        self.assertIsNone(event["error_message"])

    def test_failure_event_carries_payload_tool_use_id_and_tool_name(self):
        payload = get_failure_payload(tool_name="Read")

        event = post_tool.build_event(payload)

        self.assertEqual(event["tool_use_id"], "toolu_example_1")
        self.assertEqual(event["tool_name"], "Read")

    def test_failed_bash_test_command_reads_test_result_from_error_text(self):
        payload = get_failure_payload(
            tool_name="Bash",
            tool_input={"command": "python -m pytest -q"},
            error="Exit code 1\n2 failed, 3 passed in 0.10s",
        )

        event = post_tool.build_event(payload)

        self.assertEqual(event["test"], {"test_passed": 3, "test_failed": 2, "test_outcome": "failed"})

    def test_failed_bash_test_command_without_failed_count_has_failed_outcome(self):
        payload = get_failure_payload(
            tool_name="Bash",
            tool_input={"command": "python -m pytest -q"},
            error="Exit code 1\n3 passed in 0.10s",
        )

        event = post_tool.build_event(payload)

        self.assertEqual(event["test"], {"test_passed": 3, "test_failed": None, "test_outcome": "failed"})

    def test_failed_powershell_test_command_reads_test_result_from_error_text(self):
        payload = get_failure_payload(
            tool_name="PowerShell",
            tool_input={"command": "Invoke-Pester"},
            error="Exit code 1\n4 passed, 1 failed",
        )

        event = post_tool.build_event(payload)

        self.assertEqual(event["test"], {"test_passed": 4, "test_failed": 1, "test_outcome": "failed"})


def get_successful_test_command_payload(tool_response, tool_name="Bash"):
    return {
        "session_id": "session-a",
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": {"command": "python -m pytest -q"},
        "tool_use_id": "toolu_example_3",
        "tool_response": tool_response,
    }


class SuccessfulShellTestOutput(unittest.TestCase):
    def test_successful_bash_test_command_reads_test_result_from_stdout(self):
        payload = get_successful_test_command_payload({"stdout": "3 passed, 1 failed in 0.20s", "stderr": ""})

        event = post_tool.build_event(payload)

        self.assertEqual(event["test"], {"test_passed": 3, "test_failed": 1, "test_outcome": "failed"})

    def test_successful_powershell_test_command_reads_test_result_from_stdout(self):
        tool_response = {"stdout": "4 passed in 0.10s", "stderr": ""}
        payload = get_successful_test_command_payload(tool_response, tool_name="PowerShell")

        event = post_tool.build_event(payload)

        self.assertEqual(event["test"], {"test_passed": 4, "test_failed": None, "test_outcome": "passed"})

    def test_test_summary_only_in_stderr_is_parsed(self):
        payload = get_successful_test_command_payload({"stdout": "", "stderr": "5 passed in 0.10s"})

        event = post_tool.build_event(payload)

        self.assertEqual(event["test"], {"test_passed": 5, "test_failed": None, "test_outcome": "passed"})

    def test_counts_split_across_stdout_and_stderr_are_both_read(self):
        payload = get_successful_test_command_payload({"stdout": "3 passed", "stderr": "2 failed"})

        event = post_tool.build_event(payload)

        self.assertEqual(event["test"], {"test_passed": 3, "test_failed": 2, "test_outcome": "failed"})

    def test_passed_count_in_stdout_wins_over_passed_count_in_stderr(self):
        payload = get_successful_test_command_payload({"stdout": "3 passed", "stderr": "5 passed"})

        event = post_tool.build_event(payload)

        self.assertEqual(event["test"]["test_passed"], 3)

    def test_missing_stdout_counts_as_empty(self):
        payload = get_successful_test_command_payload({"stderr": "5 passed"})

        event = post_tool.build_event(payload)

        self.assertEqual(event["test"], {"test_passed": 5, "test_failed": None, "test_outcome": "passed"})

    def test_non_string_stdout_counts_as_empty(self):
        payload = get_successful_test_command_payload({"stdout": 42, "stderr": "5 passed"})

        event = post_tool.build_event(payload)

        self.assertEqual(event["test"], {"test_passed": 5, "test_failed": None, "test_outcome": "passed"})

    def test_test_summary_only_in_content_is_not_read(self):
        payload = get_successful_test_command_payload({"content": "5 passed", "stdout": "", "stderr": ""})

        event = post_tool.build_event(payload)

        self.assertEqual(event["test"], {"test_passed": None, "test_failed": None, "test_outcome": "unknown"})


class NoRedFlags(unittest.TestCase):
    def test_failure_reading_like_permission_denial_writes_no_red_flag(self):
        payload = get_failure_payload(error="Permission denied by user")

        events = read_events_written_by_main(payload)

        phases = [event["phase"] for event in events]
        self.assertEqual(phases, ["post_tool"])

    def test_successful_tool_reading_like_permission_denial_writes_no_red_flag(self):
        payload = {
            "session_id": "session-a",
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/example/locked.txt"},
            "tool_use_id": "toolu_example_2",
            "tool_response": {"is_error": True, "content": "Permission denied"},
        }

        events = read_events_written_by_main(payload)

        phases = [event["phase"] for event in events]
        self.assertEqual(phases, ["post_tool"])


if __name__ == "__main__":
    unittest.main()
