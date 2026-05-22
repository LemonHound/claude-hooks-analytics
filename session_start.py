import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import append_event, now_iso, read_stdin_json


def main():
    payload = read_stdin_json()
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"

    event = {
        "phase": "session_start",
        "session_id": session_id,
        "timestamp": now_iso(),
        "source": payload.get("source"),
        "cwd": payload.get("cwd"),
        "transcript_path": payload.get("transcript_path") or payload.get("transcriptPath"),
        "model": payload.get("model"),
        "account_tag": os.environ.get("CLAUDE_SESSION_TAG") or os.environ.get("CLAUDE_ACCOUNT_TAG"),
    }
    append_event(session_id, event)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
