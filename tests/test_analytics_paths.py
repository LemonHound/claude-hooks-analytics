import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analytics"))
import analyze
import dashboard


class AnalyticsPathResolution(unittest.TestCase):
    def test_override_wins(self):
        self.assertEqual(analyze._resolve_runs_dir(override="/x", env={}, config_path="/none"), Path("/x"))
        self.assertEqual(dashboard._resolve_runs_dir(override="/x", env={}, config_path="/none"), Path("/x"))

    def test_env_used(self):
        self.assertEqual(
            analyze._resolve_runs_dir(override=None, env={"CLAUDE_HOOKS_RUNS_DIR": "/y"}, config_path="/none"),
            Path(os.path.expanduser("/y")),
        )

    def test_config_used(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "installer_config.json"
            cfg.write_text(json.dumps({"runs_dir": "/data/runs"}), encoding="utf-8")
            self.assertEqual(
                dashboard._resolve_runs_dir(override=None, env={}, config_path=str(cfg)),
                Path(os.path.expanduser("/data/runs")),
            )

    def test_default(self):
        self.assertEqual(
            analyze._resolve_runs_dir(override=None, env={}, config_path="/none"),
            Path.home() / ".claude" / "runs",
        )


if __name__ == "__main__":
    unittest.main()
