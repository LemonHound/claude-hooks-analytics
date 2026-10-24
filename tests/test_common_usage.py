import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import _common


COUNTED_USAGE = {
    "input_tokens": 10,
    "output_tokens": 20,
    "cache_read_input_tokens": 30,
    "cache_creation_input_tokens": 40,
}


class SubagentCountedUsage(unittest.TestCase):
    def setUp(self):
        events_dir = tempfile.TemporaryDirectory()
        self.addCleanup(events_dir.cleanup)
        events_dir_patch = mock.patch.object(_common, "EVENTS_DIR", Path(events_dir.name))
        events_dir_patch.start()
        self.addCleanup(events_dir_patch.stop)

    def test_returns_none_when_nothing_was_counted_for_the_agent(self):
        counted_usage = _common.read_subagent_counted_usage("session-a", "agent-1")

        self.assertIsNone(counted_usage)

    def test_returns_the_counted_usage_written_for_the_agent(self):
        _common.write_subagent_counted_usage("session-a", "agent-1", COUNTED_USAGE)

        counted_usage = _common.read_subagent_counted_usage("session-a", "agent-1")

        self.assertEqual(counted_usage, COUNTED_USAGE)

    def test_does_not_return_another_agents_counted_usage(self):
        _common.write_subagent_counted_usage("session-a", "agent-1", COUNTED_USAGE)

        counted_usage = _common.read_subagent_counted_usage("session-a", "agent-2")

        self.assertIsNone(counted_usage)


if __name__ == "__main__":
    unittest.main()
