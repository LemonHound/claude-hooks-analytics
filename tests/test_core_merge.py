import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from installer import core

SESSION_START = {"event": "SessionStart", "matcher": None, "async": True, "script": "session_start.py", "kind": "hook", "timeout": None}
SESSION_END = {"event": "Stop", "matcher": None, "async": True, "script": "session_end.py", "kind": "hook", "timeout": None}
MANAGED = ["session_start.py", "session_end.py", "pre_tool.py"]


class CoreMerge(unittest.TestCase):
    def test_preserves_non_hook_settings(self):
        settings = {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {}}
        out = core.merge_settings(settings, [SESSION_START], "py", "/new/hooks", MANAGED)
        self.assertEqual(out["permissions"], {"allow": ["Bash(ls)"]})

    def test_preserves_foreign_hooks(self):
        settings = {"hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": "python /other/foreign.py", "async": False}]}]}}
        out = core.merge_settings(settings, [SESSION_START], "py", "/new/hooks", MANAGED)
        cmds = [h["command"] for e in out["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertIn("python /other/foreign.py", cmds)

    def test_replaces_stale_entry_for_relocated_hook(self):
        settings = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": '"py" "/old/hooks/session_start.py"', "async": True}]}]}}
        out = core.merge_settings(settings, [SESSION_START], "py", "/new/hooks", MANAGED)
        cmds = [h["command"] for e in out["hooks"]["SessionStart"] for h in e["hooks"]]
        self.assertEqual(len(cmds), 1)
        self.assertIn("/new/hooks/session_start.py", cmds[0])
        self.assertNotIn("/old/hooks", cmds[0])

    def test_removes_deselected_component(self):
        settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": '"py" "/h/session_end.py"', "async": True}]}]}}
        out = core.merge_settings(settings, [], "py", "/h", MANAGED)
        self.assertNotIn("Stop", out["hooks"])

    def test_adds_selected_when_absent(self):
        out = core.merge_settings({}, [SESSION_END], "py", "/h", MANAGED)
        cmds = [h["command"] for e in out["hooks"]["Stop"] for h in e["hooks"]]
        self.assertEqual(cmds, ['"py" "/h/session_end.py"'])


if __name__ == "__main__":
    unittest.main()
