import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import _common
import session_end


def get_pre_tool(tool_use_id, tool_name="Bash"):
    return {"phase": "pre_tool", "tool_use_id": tool_use_id, "tool_name": tool_name, "_epoch": 10.0}


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
            "tool_name": "Read",
            "tool_use_id": "toolu_1",
        }
        events = [get_pre_tool("toolu_1", tool_name="Read"), get_post_tool("toolu_1"), persisted_flag]

        counts = get_red_flag_counts(events)

        self.assertEqual(counts["permission_denied_count"], 1)
        self.assertEqual(counts["permission_denied_tools"], {"Read": 1})

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


if __name__ == "__main__":
    unittest.main()
