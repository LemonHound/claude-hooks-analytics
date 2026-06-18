import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import append_event, now_iso, read_stdin_json


def main():
    payload = read_stdin_json()
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"
    trigger = payload.get("trigger") or "unknown"
    custom = payload.get("custom_instructions") or payload.get("customInstructions") or ""

    event = {
        "phase": "compaction",
        "session_id": session_id,
        "timestamp": now_iso(),
        "trigger": trigger,
        "custom_instructions_present": bool(custom),
    }
    append_event(session_id, event)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
