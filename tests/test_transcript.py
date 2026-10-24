import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import _transcript


def get_assistant_line(message_id, input_tokens, model="model-a"):
    message = {
        "role": "assistant",
        "model": model,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": input_tokens * 2,
            "cache_read_input_tokens": input_tokens * 3,
            "cache_creation_input_tokens": input_tokens * 4,
        },
    }
    if message_id is not None:
        message["id"] = message_id
    return json.dumps({"message": message})


def get_assistant_line_with_output_tokens(message_id, output_tokens):
    message = {
        "role": "assistant",
        "id": message_id,
        "model": "model-a",
        "usage": {
            "input_tokens": 10,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": 30,
            "cache_creation_input_tokens": 40,
        },
    }
    return json.dumps({"message": message})


def read_usage_of_transcript(lines):
    with tempfile.TemporaryDirectory() as transcript_dir:
        transcript_path = Path(transcript_dir) / "transcript.jsonl"
        transcript_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return _transcript.read_transcript_usage(transcript_path)


def get_expected_token_sums(input_tokens):
    return {
        "input_tokens": input_tokens,
        "output_tokens": input_tokens * 2,
        "cache_read_input_tokens": input_tokens * 3,
        "cache_creation_input_tokens": input_tokens * 4,
    }


def get_token_sums_of_usage(usage):
    return {
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cache_read_input_tokens": usage["cache_read_input_tokens"],
        "cache_creation_input_tokens": usage["cache_creation_input_tokens"],
    }


class ReadTranscriptUsage(unittest.TestCase):
    def test_counts_lines_sharing_one_message_id_once(self):
        lines = [get_assistant_line("msg_1", 10), get_assistant_line("msg_1", 10), get_assistant_line("msg_1", 10)]

        usage = read_usage_of_transcript(lines)

        self.assertEqual(get_token_sums_of_usage(usage), get_expected_token_sums(10))

    def test_counts_last_line_of_message_id_when_output_tokens_grow_across_lines(self):
        lines = [
            get_assistant_line_with_output_tokens("msg_1", 1),
            get_assistant_line_with_output_tokens("msg_1", 5),
            get_assistant_line_with_output_tokens("msg_1", 9),
        ]

        usage = read_usage_of_transcript(lines)

        expected_token_sums = {
            "input_tokens": 10,
            "output_tokens": 9,
            "cache_read_input_tokens": 30,
            "cache_creation_input_tokens": 40,
        }
        self.assertEqual(get_token_sums_of_usage(usage), expected_token_sums)

    def test_zero_usage_line_does_not_replace_earlier_usage_of_message_id(self):
        lines = [get_assistant_line("msg_1", 7), get_assistant_line("msg_1", 0)]

        usage = read_usage_of_transcript(lines)

        self.assertEqual(get_token_sums_of_usage(usage), get_expected_token_sums(7))

    def test_counts_each_line_without_message_id(self):
        lines = [get_assistant_line(None, 10), get_assistant_line(None, 10)]

        usage = read_usage_of_transcript(lines)

        self.assertEqual(get_token_sums_of_usage(usage), get_expected_token_sums(20))

    def test_counts_each_line_with_empty_message_id(self):
        lines = [get_assistant_line("", 10), get_assistant_line("", 10)]

        usage = read_usage_of_transcript(lines)

        self.assertEqual(get_token_sums_of_usage(usage), get_expected_token_sums(20))

    def test_counts_messages_with_different_ids_once_each(self):
        lines = [get_assistant_line("msg_1", 10), get_assistant_line("msg_2", 5), get_assistant_line("msg_2", 5)]

        usage = read_usage_of_transcript(lines)

        self.assertEqual(get_token_sums_of_usage(usage), get_expected_token_sums(15))

    def test_dominant_model_counts_every_line_with_usage(self):
        lines = [
            get_assistant_line("msg_1", 10, model="model-b"),
            get_assistant_line("msg_2", 10, model="model-b"),
            get_assistant_line("msg_3", 10, model="model-a"),
            get_assistant_line("msg_3", 10, model="model-a"),
            get_assistant_line("msg_3", 10, model="model-a"),
        ]

        usage = read_usage_of_transcript(lines)

        self.assertEqual(usage["dominant_model"], "model-a")


if __name__ == "__main__":
    unittest.main()
