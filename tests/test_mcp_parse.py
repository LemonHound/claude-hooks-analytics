import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from _segments import parse_mcp_tool


class McpParse(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(parse_mcp_tool("mcp__github__create_issue"), ("github", "create_issue"))

    def test_tool_with_double_underscores(self):
        self.assertEqual(parse_mcp_tool("mcp__my_server__do__thing"), ("my_server", "do__thing"))

    def test_non_mcp(self):
        self.assertEqual(parse_mcp_tool("Bash"), (None, None))


if __name__ == "__main__":
    unittest.main()
