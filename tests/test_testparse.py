import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from _testparse import parse_test_output


class TestParse(unittest.TestCase):
    def test_pytest_passed(self):
        r = parse_test_output("=== 5 passed in 0.10s ===", False)
        self.assertEqual(r["test_passed"], 5)
        self.assertEqual(r["test_outcome"], "passed")

    def test_pytest_failed(self):
        r = parse_test_output("1 failed, 4 passed in 0.2s", False)
        self.assertEqual(r["test_failed"], 1)
        self.assertEqual(r["test_outcome"], "failed")

    def test_error_flag_is_failed(self):
        r = parse_test_output("no counts here", True)
        self.assertEqual(r["test_outcome"], "failed")

    def test_unknown_when_no_signal(self):
        r = parse_test_output("ran something", False)
        self.assertEqual(r["test_outcome"], "unknown")


if __name__ == "__main__":
    unittest.main()
