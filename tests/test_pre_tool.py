import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import pre_tool


def get_read_payload():
    return {
        "session_id": "session-a",
        "tool_name": "Read",
        "tool_input": {"file_path": "/example/notes.txt"},
        "tool_use_id": "toolu_example_1",
    }


def get_read_payload_inside_subagent():
    payload = get_read_payload()
    payload["agent_id"] = "agent-1"
    payload["agent_type"] = "outer-agent"
    return payload


class CallingAgent(unittest.TestCase):
    def test_records_payload_agent_id_and_agent_type_as_calling_agent(self):
        payload = get_read_payload_inside_subagent()

        event = pre_tool.build_event(payload)

        self.assertEqual(event["calling_agent_id"], "agent-1")
        self.assertEqual(event["calling_agent_type"], "outer-agent")

    def test_calling_agent_is_null_when_payload_lacks_agent_fields(self):
        payload = get_read_payload()

        event = pre_tool.build_event(payload)

        self.assertIsNone(event["calling_agent_id"])
        self.assertIsNone(event["calling_agent_type"])

    def test_non_dispatch_call_inside_subagent_keeps_agent_type_null(self):
        payload = get_read_payload_inside_subagent()

        event = pre_tool.build_event(payload)

        self.assertIsNone(event["agent_type"])

    def test_agent_dispatch_inside_subagent_keeps_dispatched_type_in_agent_type(self):
        payload = {
            "session_id": "session-a",
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "inner-agent", "description": "Example task"},
            "tool_use_id": "toolu_example_2",
            "agent_id": "agent-1",
            "agent_type": "outer-agent",
        }

        event = pre_tool.build_event(payload)

        self.assertEqual(event["agent_type"], "inner-agent")
        self.assertEqual(event["calling_agent_type"], "outer-agent")


if __name__ == "__main__":
    unittest.main()
