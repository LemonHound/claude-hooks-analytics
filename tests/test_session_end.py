import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import _common
import session_end


def get_pre_tool(tool_use_id):
    return {"phase": "pre_tool", "tool_use_id": tool_use_id, "tool_name": "Bash", "_epoch": 10.0}


def get_post_tool(tool_use_id, is_error=False):
    return {"phase": "post_tool", "tool_use_id": tool_use_id, "tool_name": "Bash", "is_error": is_error, "_epoch": 11.0}


def get_red_flag_counts(events):
    rollup = session_end.build_rollup(events, None, {"session_id": "session-a"}, artifacts=[])
    return {
        "red_flag_count": rollup["red_flag_count"],
        "red_flag_kinds": rollup["red_flag_kinds"],
        "permission_denied_count": rollup["permission_denied_count"],
        "permission_denied_tools": rollup["permission_denied_tools"],
    }


class RollupRedFlags(unittest.TestCase):
    def test_counts_permission_denied_flag_for_pre_tool_without_post_tool(self):
        events = [get_pre_tool("toolu_1")]

        counts = get_red_flag_counts(events)

        self.assertEqual(counts["permission_denied_count"], 1)
        self.assertEqual(counts["permission_denied_tools"], {"Bash": 1})

    def test_counts_no_permission_denied_flag_for_pre_tool_paired_with_successful_post_tool(self):
        events = [get_pre_tool("toolu_1"), get_post_tool("toolu_1")]

        counts = get_red_flag_counts(events)

        self.assertEqual(counts["permission_denied_count"], 0)
        self.assertEqual(counts["permission_denied_tools"], {})

    def test_counts_no_permission_denied_flag_for_pre_tool_paired_with_failure_post_tool(self):
        events = [get_pre_tool("toolu_1"), get_post_tool("toolu_1", is_error=True)]

        counts = get_red_flag_counts(events)

        self.assertEqual(counts["permission_denied_count"], 0)
        self.assertEqual(counts["permission_denied_tools"], {})

    def test_ignores_persisted_missing_post_tool_flag(self):
        persisted_flag = {
            "phase": "red_flag",
            "kind": "permission_denied",
            "inferred_from": "missing_post_tool",
            "tool_name": "Bash",
            "tool_use_id": "toolu_1",
        }
        events = [get_pre_tool("toolu_1"), persisted_flag, get_post_tool("toolu_1")]

        counts = get_red_flag_counts(events)

        self.assertEqual(counts["red_flag_count"], 0)
        self.assertEqual(counts["permission_denied_count"], 0)

    def test_counts_persisted_post_edit_check_flag(self):
        persisted_flag = {"phase": "red_flag", "kind": "post_edit_check", "tool_use_id": "toolu_1"}
        events = [get_pre_tool("toolu_1"), get_post_tool("toolu_1"), persisted_flag]

        counts = get_red_flag_counts(events)

        self.assertEqual(counts["red_flag_count"], 1)
        self.assertEqual(counts["red_flag_kinds"], ["post_edit_check"])

    def test_counts_persisted_is_error_signature_permission_denied_flag(self):
        persisted_flag = {
            "phase": "red_flag",
            "kind": "permission_denied",
            "inferred_from": "is_error_signature",
            "tool_name": "Bash",
            "tool_use_id": "toolu_1",
        }
        events = [get_pre_tool("toolu_1"), get_post_tool("toolu_1"), persisted_flag]

        counts = get_red_flag_counts(events)

        self.assertEqual(counts["permission_denied_count"], 1)
        self.assertEqual(counts["permission_denied_tools"], {"Bash": 1})

    def test_red_flag_count_sums_derived_and_persisted_flags(self):
        persisted_flag = {"phase": "red_flag", "kind": "post_edit_check", "tool_use_id": "toolu_2"}
        events = [get_pre_tool("toolu_1"), persisted_flag]

        counts = get_red_flag_counts(events)

        self.assertEqual(counts["red_flag_count"], 2)
        self.assertEqual(counts["red_flag_kinds"], ["permission_denied", "post_edit_check"])


class StopWritesNoFlags(unittest.TestCase):
    def test_stop_appends_no_red_flag_event_to_events_file(self):
        with tempfile.TemporaryDirectory() as runs_dir:
            runs_path = Path(runs_dir)
            events_file = runs_path / "session-a.jsonl"
            events_file.write_text(json.dumps(get_pre_tool("toolu_1")) + "\n", encoding="utf-8")
            stop_payload = json.dumps({"session_id": "session-a"}).encode("utf-8")
            fake_stdin = io.TextIOWrapper(io.BytesIO(stop_payload), encoding="utf-8")
            with mock.patch.object(_common, "EVENTS_DIR", runs_path), \
                    mock.patch.object(_common, "SESSIONS_DIR", runs_path), \
                    mock.patch.object(session_end, "ARTIFACTS_DIR", runs_path / "artifacts"), \
                    mock.patch.object(sys, "stdin", fake_stdin):
                session_end.main()
            lines = events_file.read_text(encoding="utf-8").splitlines()

        phases = []
        for line in lines:
            phases.append(json.loads(line)["phase"])
        self.assertNotIn("red_flag", phases)


TURN_START_EPOCH = 1792800000.0


def get_assistant_line(usage, seconds_after_turn_start=10):
    message_epoch = TURN_START_EPOCH + seconds_after_turn_start
    timestamp = datetime.fromtimestamp(message_epoch, timezone.utc).isoformat()
    message = {"role": "assistant", "model": "model-a", "usage": usage}
    return json.dumps({"timestamp": timestamp, "message": message})


LARGE_INPUT_SMALL_CONTEXT_USAGE = {"input_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
LARGEST_CONTEXT_USAGE = {"input_tokens": 5, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 200}
LAST_CONTEXT_USAGE = {"input_tokens": 4, "cache_read_input_tokens": 300, "cache_creation_input_tokens": 6}


class ContextTokens(unittest.TestCase):
    def setUp(self):
        transcript_dir = tempfile.TemporaryDirectory()
        self.addCleanup(transcript_dir.cleanup)
        self.transcript_path = Path(transcript_dir.name) / "transcript.jsonl"

    def write_transcript(self, lines):
        self.transcript_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def build_rollup_of_transcript(self):
        return session_end.build_rollup([], str(self.transcript_path), {"session_id": "session-a"}, artifacts=[])

    def build_single_turn_of_transcript(self):
        events = [
            {"phase": "user_prompt_submit", "prompt_hash": "prompt-a", "_epoch": TURN_START_EPOCH},
            {"phase": "session_end", "_epoch": TURN_START_EPOCH + 100},
        ]
        turns = session_end.build_turn_summaries(events, str(self.transcript_path))
        self.assertEqual(len(turns), 1)
        return turns[0]

    def test_rollup_peak_is_the_largest_input_plus_cache_tokens(self):
        self.write_transcript([
            get_assistant_line(LARGE_INPUT_SMALL_CONTEXT_USAGE),
            get_assistant_line(LARGEST_CONTEXT_USAGE),
            get_assistant_line(LAST_CONTEXT_USAGE),
        ])

        rollup = self.build_rollup_of_transcript()

        self.assertEqual(rollup["peak_input_tokens"], 1205)

    def test_rollup_final_is_input_plus_cache_tokens_of_the_last_message(self):
        self.write_transcript([
            get_assistant_line(LARGEST_CONTEXT_USAGE),
            get_assistant_line(LAST_CONTEXT_USAGE),
        ])

        rollup = self.build_rollup_of_transcript()

        self.assertEqual(rollup["final_input_tokens"], 310)

    def test_missing_usage_field_counts_as_zero_in_context_size(self):
        self.write_transcript([get_assistant_line({"input_tokens": 5, "cache_read_input_tokens": 100})])

        rollup = self.build_rollup_of_transcript()

        self.assertEqual(rollup["final_input_tokens"], 105)

    def test_non_int_usage_field_counts_as_zero_in_context_size(self):
        usage = {"input_tokens": 5, "cache_read_input_tokens": "100", "cache_creation_input_tokens": 7}
        self.write_transcript([get_assistant_line(usage)])

        rollup = self.build_rollup_of_transcript()

        self.assertEqual(rollup["final_input_tokens"], 12)

    def test_turn_peak_is_the_largest_input_plus_cache_tokens_in_its_window(self):
        self.write_transcript([
            get_assistant_line(LARGE_INPUT_SMALL_CONTEXT_USAGE, seconds_after_turn_start=10),
            get_assistant_line(LARGEST_CONTEXT_USAGE, seconds_after_turn_start=20),
            get_assistant_line(LAST_CONTEXT_USAGE, seconds_after_turn_start=30),
        ])

        turn = self.build_single_turn_of_transcript()

        self.assertEqual(turn["peak_input_tokens"], 1205)

    def test_turn_final_is_input_plus_cache_tokens_of_its_last_message(self):
        self.write_transcript([
            get_assistant_line(LARGEST_CONTEXT_USAGE, seconds_after_turn_start=10),
            get_assistant_line(LAST_CONTEXT_USAGE, seconds_after_turn_start=20),
        ])

        turn = self.build_single_turn_of_transcript()

        self.assertEqual(turn["final_input_tokens"], 310)


if __name__ == "__main__":
    unittest.main()
