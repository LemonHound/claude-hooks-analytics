import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from _churn import compute_churn


class Churn(unittest.TestCase):
    def test_edit_counts_both_sides(self):
        r = compute_churn("Edit", {"old_string": "a\nb", "new_string": "a\nb\nc\nd"})
        self.assertEqual(r, {"lines_added": 4, "lines_removed": 2})

    def test_multiedit_sums(self):
        r = compute_churn("MultiEdit", {"edits": [{"old_string": "a", "new_string": "a\nb"}, {"old_string": "", "new_string": "x"}]})
        self.assertEqual(r, {"lines_added": 3, "lines_removed": 1})

    def test_write_added_only(self):
        r = compute_churn("Write", {"content": "a\nb\nc"})
        self.assertEqual(r, {"lines_added": 3, "lines_removed": 0})

    def test_non_edit_is_zero(self):
        r = compute_churn("Bash", {"command": "ls"})
        self.assertEqual(r, {"lines_added": 0, "lines_removed": 0})


if __name__ == "__main__":
    unittest.main()
