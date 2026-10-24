import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from installer.manifest import COMPONENTS, managed_scripts


class Manifest(unittest.TestCase):
    def test_hook_components_have_required_keys(self):
        for c in COMPONENTS:
            if c["kind"] == "hook":
                for k in ("id", "label", "description", "event", "script"):
                    self.assertIn(k, c, f"{c.get('id')} missing {k}")

    def test_all_referenced_scripts_exist(self):
        for c in COMPONENTS:
            script = c.get("script")
            if script:
                self.assertTrue((REPO / "hooks" / script).exists(), script)

    def test_tool_paths_exist(self):
        for c in COMPONENTS:
            if c["kind"] == "tool":
                self.assertTrue((REPO / c["path"]).exists(), c["path"])

    def test_post_tool_failure_hook_runs_post_tool_for_every_tool_asynchronously(self):
        failure_hooks = [c for c in COMPONENTS if c.get("event") == "PostToolUseFailure"]

        self.assertEqual(len(failure_hooks), 1)
        failure_hook = failure_hooks[0]
        self.assertEqual(failure_hook["kind"], "hook")
        self.assertEqual(failure_hook["matcher"], ".*")
        self.assertEqual(failure_hook["async"], True)
        self.assertEqual(failure_hook["script"], "post_tool.py")
        self.assertEqual(failure_hook["default_enabled"], True)

    def test_managed_scripts_lists_every_hook_and_support(self):
        expected = {c["script"] for c in COMPONENTS if c.get("script")}
        self.assertEqual(set(managed_scripts()), expected)


if __name__ == "__main__":
    unittest.main()
