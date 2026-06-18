import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from installer import core


class CoreEntries(unittest.TestCase):
    def test_default_paths(self):
        p = core.default_paths()
        self.assertEqual(p["settings_path"], Path(os.path.expanduser("~")) / ".claude" / "settings.json")

    def test_hook_command_uses_forward_slashes_and_quotes(self):
        cmd = core.hook_command("C:\\Py\\python.exe", "C:\\h", "pre_tool.py")
        self.assertEqual(cmd, '"C:/Py/python.exe" "C:/h/pre_tool.py"')

    def test_build_entry_with_matcher(self):
        comp = {"event": "PreToolUse", "matcher": ".*", "async": False, "script": "pre_tool.py", "kind": "hook", "timeout": None}
        event, entry = core.build_hook_entry(comp, "py", "/h")
        self.assertEqual(event, "PreToolUse")
        self.assertEqual(entry["matcher"], ".*")
        self.assertIs(entry["hooks"][0]["async"], False)
        self.assertEqual(entry["hooks"][0]["command"], '"py" "/h/pre_tool.py"')

    def test_build_entry_without_matcher_omits_key(self):
        comp = {"event": "SessionStart", "matcher": None, "async": True, "script": "session_start.py", "kind": "hook", "timeout": None}
        event, entry = core.build_hook_entry(comp, "py", "/h")
        self.assertNotIn("matcher", entry)
        self.assertIs(entry["hooks"][0]["async"], True)


if __name__ == "__main__":
    unittest.main()
