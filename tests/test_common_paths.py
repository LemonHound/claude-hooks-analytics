import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import _common


class CommonPathResolution(unittest.TestCase):
    def test_env_var_wins(self):
        d = _common.resolve_runs_dir(env={"CLAUDE_HOOKS_RUNS_DIR": "/tmp/foo"}, config_path="/does/not/exist")
        self.assertEqual(d, Path(os.path.expanduser("/tmp/foo")))

    def test_config_file_used_when_no_env(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "installer_config.json"
            cfg.write_text(json.dumps({"runs_dir": "/data/runs"}), encoding="utf-8")
            d = _common.resolve_runs_dir(env={}, config_path=str(cfg))
            self.assertEqual(d, Path(os.path.expanduser("/data/runs")))

    def test_default_when_nothing_set(self):
        d = _common.resolve_runs_dir(env={}, config_path="/nope/installer_config.json")
        self.assertEqual(d, Path(os.path.expanduser("~/.claude/runs")))


if __name__ == "__main__":
    unittest.main()
