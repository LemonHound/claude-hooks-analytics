import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import _common
import subagent_stop


def get_assistant_line(message_id, input_tokens):
    message = {
        "role": "assistant",
        "id": message_id,
        "model": "model-a",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": input_tokens * 2,
            "cache_read_input_tokens": input_tokens * 3,
            "cache_creation_input_tokens": input_tokens * 4,
        },
    }
    return json.dumps({"message": message}) + "\n"


def get_artifact_tokens(input_tokens):
    return {
        "input_tokens": input_tokens,
        "output_tokens": input_tokens * 2,
        "cache_read_tokens": input_tokens * 3,
        "cache_creation_tokens": input_tokens * 4,
    }


def get_tokens_of_artifact(artifact):
    return {
        "input_tokens": artifact["input_tokens"],
        "output_tokens": artifact["output_tokens"],
        "cache_read_tokens": artifact["cache_read_tokens"],
        "cache_creation_tokens": artifact["cache_creation_tokens"],
    }


class SubagentStopTokens(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        temp_path = Path(temp_dir.name)
        self.events_dir = temp_path / "events"
        self.artifacts_dir = temp_path / "artifacts"
        self.events_dir.mkdir()
        self.artifacts_dir.mkdir()
        self.transcript_path = temp_path / "agent-transcript.jsonl"
        self.transcript_path.write_text("", encoding="utf-8")
        for name, value in (("EVENTS_DIR", self.events_dir), ("ARTIFACTS_DIR", self.artifacts_dir)):
            dir_patch = mock.patch.object(_common, name, value)
            dir_patch.start()
            self.addCleanup(dir_patch.stop)

    def append_transcript_lines(self, lines):
        with self.transcript_path.open("a", encoding="utf-8") as transcript_file:
            for line in lines:
                transcript_file.write(line)

    def run_stop_and_take_artifact(self, agent_id):
        payload = {
            "session_id": "session-a",
            "agent_type": "example-agent",
            "agent_transcript_path": str(self.transcript_path),
        }
        if agent_id is not None:
            payload["agent_id"] = agent_id
        payload_bytes = json.dumps(payload).encode("utf-8")
        fake_stdin = io.TextIOWrapper(io.BytesIO(payload_bytes), encoding="utf-8")
        with mock.patch.object(sys, "stdin", fake_stdin):
            subagent_stop.main()
        artifact_paths = list(self.artifacts_dir.glob("*.json"))
        self.assertEqual(len(artifact_paths), 1)
        artifact = json.loads(artifact_paths[0].read_text(encoding="utf-8"))
        artifact_paths[0].unlink()
        return artifact

    def get_counted_usage_files(self):
        return list(self.events_dir.glob("*_usage.json"))

    def test_first_artifact_of_agent_carries_deduped_transcript_total(self):
        self.append_transcript_lines([get_assistant_line("msg_1", 10), get_assistant_line("msg_1", 10)])

        artifact = self.run_stop_and_take_artifact("agent-1")

        self.assertEqual(get_tokens_of_artifact(artifact), get_artifact_tokens(10))

    def test_later_artifact_of_agent_carries_only_usage_of_new_messages(self):
        self.append_transcript_lines([get_assistant_line("msg_1", 10)])
        self.run_stop_and_take_artifact("agent-1")
        self.append_transcript_lines([get_assistant_line("msg_2", 7), get_assistant_line("msg_2", 7)])

        artifact = self.run_stop_and_take_artifact("agent-1")

        self.assertEqual(get_tokens_of_artifact(artifact), get_artifact_tokens(7))

    def test_third_artifact_of_agent_carries_only_usage_of_messages_added_since_second(self):
        self.append_transcript_lines([get_assistant_line("msg_1", 10)])
        self.run_stop_and_take_artifact("agent-1")
        self.append_transcript_lines([get_assistant_line("msg_2", 7)])
        self.run_stop_and_take_artifact("agent-1")
        self.append_transcript_lines([get_assistant_line("msg_3", 5)])

        artifact = self.run_stop_and_take_artifact("agent-1")

        self.assertEqual(get_tokens_of_artifact(artifact), get_artifact_tokens(5))

    def test_later_artifact_of_agent_without_new_messages_carries_zero_tokens(self):
        self.append_transcript_lines([get_assistant_line("msg_1", 10)])
        self.run_stop_and_take_artifact("agent-1")

        artifact = self.run_stop_and_take_artifact("agent-1")

        self.assertEqual(get_tokens_of_artifact(artifact), get_artifact_tokens(0))

    def test_artifact_is_not_reduced_by_usage_counted_for_another_agent(self):
        self.append_transcript_lines([get_assistant_line("msg_1", 10)])
        self.run_stop_and_take_artifact("agent-1")

        artifact = self.run_stop_and_take_artifact("agent-2")

        self.assertEqual(get_tokens_of_artifact(artifact), get_artifact_tokens(10))

    def test_artifacts_without_agent_id_carry_full_total_and_write_no_counted_usage(self):
        self.append_transcript_lines([get_assistant_line("msg_1", 10)])
        self.run_stop_and_take_artifact(None)

        artifact = self.run_stop_and_take_artifact(None)

        self.assertEqual(get_tokens_of_artifact(artifact), get_artifact_tokens(10))
        self.assertEqual(self.get_counted_usage_files(), [])

    def test_artifact_without_transcript_usage_uses_post_tool_sums_and_writes_no_counted_usage(self):
        post_tool_event = {
            "phase": "post_tool",
            "tool_use_id": "toolu_1",
            "input_tokens": 3,
            "output_tokens": 6,
            "cache_read_tokens": 9,
            "cache_creation_tokens": 12,
            "_epoch": 1.0,
        }
        events_file = self.events_dir / "session-a.jsonl"
        events_file.write_text(json.dumps(post_tool_event) + "\n", encoding="utf-8")

        artifact = self.run_stop_and_take_artifact("agent-1")

        self.assertEqual(get_tokens_of_artifact(artifact), get_artifact_tokens(3))
        self.assertEqual(self.get_counted_usage_files(), [])


if __name__ == "__main__":
    unittest.main()
