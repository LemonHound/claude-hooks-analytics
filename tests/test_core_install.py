import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from installer import core
from installer.manifest import COMPONENTS, managed_scripts

SRC_HOOKS = REPO / "hooks"


def _by_id(*ids):
    return [c for c in COMPONENTS if c["id"] in ids]


class CoreInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.hooks = self.base / "hooks"
        self.runs = self.base / "runs"
        self.settings = self.base / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_copies_scripts_shared_and_support(self):
        core.install(_by_id("session_start", "record_subagent_feedback"), self.hooks, self.runs, self.settings, "py", SRC_HOOKS, managed_scripts())
        self.assertTrue((self.hooks / "session_start.py").exists())
        self.assertTrue((self.hooks / "_common.py").exists())
        self.assertTrue((self.hooks / "record_subagent_feedback.py").exists())

    def test_install_writes_config_and_dirs(self):
        core.install(_by_id("session_start"), self.hooks, self.runs, self.settings, "py", SRC_HOOKS, managed_scripts())
        cfg = json.loads((self.hooks / "installer_config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["runs_dir"], str(self.runs))
        self.assertTrue((self.runs / "events").is_dir())
        self.assertTrue((self.runs / "sessions").is_dir())
        self.assertTrue((self.runs / "prompts").is_dir())

    def test_install_merges_into_existing_settings(self):
        self.settings.write_text(json.dumps({"permissions": {"x": 1}}), encoding="utf-8")
        core.install(_by_id("session_start"), self.hooks, self.runs, self.settings, "py", SRC_HOOKS, managed_scripts())
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(data["permissions"], {"x": 1})
        self.assertIn("SessionStart", data["hooks"])


if __name__ == "__main__":
    unittest.main()
