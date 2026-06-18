import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from notification import classify_notification


class Notification(unittest.TestCase):
    def test_permission_request(self):
        self.assertEqual(classify_notification("Claude needs your permission to use Bash"), "permission_request")

    def test_idle_waiting(self):
        self.assertEqual(classify_notification("Claude is waiting for your input"), "idle_waiting")

    def test_other(self):
        self.assertEqual(classify_notification("Build finished"), "other")


if __name__ == "__main__":
    unittest.main()
