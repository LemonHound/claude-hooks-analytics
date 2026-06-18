import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from installer import core


class CoreAnalytics(unittest.TestCase):
    def test_analyze_command_has_no_output_flag(self):
        cmd = core.analytics_command("py", "/repo", "analyze", "/data")
        self.assertEqual(cmd, ["py", str(Path("/repo") / "analytics" / "analyze.py"), "--runs-dir", "/data"])

    def test_dashboard_command_includes_output(self):
        cmd = core.analytics_command("py", "/repo", "dashboard", "/data", "/data/dashboard.html")
        self.assertEqual(
            cmd,
            ["py", str(Path("/repo") / "analytics" / "dashboard.py"), "--runs-dir", "/data", "--output", "/data/dashboard.html"],
        )


if __name__ == "__main__":
    unittest.main()
