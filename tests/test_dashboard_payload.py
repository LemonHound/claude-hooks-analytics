import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analytics"))
import dashboard


class DashboardPayload(unittest.TestCase):
    def test_aggregates_new_metrics(self):
        sessions = [
            {"session_id": "a", "timestamp_start": "2026-06-18T00:00:00+00:00", "lines_added": 10, "lines_removed": 3, "test_run_count": 2, "test_pass_total": 5, "test_fail_total": 1, "test_failed_runs": 1, "mcp_server_breakdown": {"github": 2}, "compaction_count": 1, "notification_count": 4, "permission_request_count": 2},
            {"session_id": "b", "timestamp_start": "2026-06-18T01:00:00+00:00", "lines_added": 5, "lines_removed": 1, "mcp_server_breakdown": {"github": 1, "slack": 3}},
        ]
        p = dashboard.build_payload(sessions, [])
        self.assertEqual(p["churn"], {"added": 15, "removed": 4, "net": 11})
        self.assertEqual(p["tests"]["runs"], 2)
        self.assertEqual(p["tests"]["failed_runs"], 1)
        self.assertEqual(p["mcp_totals"], {"github": 3, "slack": 3})
        self.assertEqual(p["compaction_total"], 1)
        self.assertEqual(p["notification_total"], 4)
        self.assertEqual(p["permission_request_total"], 2)


if __name__ == "__main__":
    unittest.main()
