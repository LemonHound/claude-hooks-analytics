import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import _common


def get_stdin_with_cp1252_text_layer(payload_bytes):
    byte_layer = io.BytesIO(payload_bytes)
    return io.TextIOWrapper(byte_layer, encoding="cp1252", errors="surrogateescape")


def read_stdin_json_from(payload_bytes):
    fake_stdin = get_stdin_with_cp1252_text_layer(payload_bytes)
    with mock.patch.object(sys, "stdin", fake_stdin):
        return _common.read_stdin_json()


class ReadStdinJson(unittest.TestCase):
    def test_returns_exact_non_ascii_characters_when_stdin_text_layer_is_cp1252(self):
        payload_bytes = '{"prompt": "héllo ✓ 日本"}'.encode("utf-8")

        result = read_stdin_json_from(payload_bytes)

        self.assertEqual(result, {"prompt": "héllo ✓ 日本"})

    def test_returns_parse_error_with_empty_raw_when_bytes_are_not_valid_utf8(self):
        payload_bytes = b'{"prompt": "\xff"}'

        result = read_stdin_json_from(payload_bytes)

        self.assertEqual(set(result), {"_parse_error", "_raw"})
        self.assertEqual(result["_raw"], "")
        self.assertIsInstance(result["_parse_error"], str)
        self.assertNotEqual(result["_parse_error"], "")

    def test_returns_parse_error_with_decoded_raw_when_json_is_malformed(self):
        payload_bytes = '{"prompt": "héllo'.encode("utf-8")

        result = read_stdin_json_from(payload_bytes)

        self.assertEqual(set(result), {"_parse_error", "_raw"})
        self.assertEqual(result["_raw"], '{"prompt": "héllo')
        self.assertIsInstance(result["_parse_error"], str)
        self.assertNotEqual(result["_parse_error"], "")

    def test_returns_empty_dict_when_stdin_is_whitespace_only(self):
        payload_bytes = b" \n\t "

        result = read_stdin_json_from(payload_bytes)

        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
