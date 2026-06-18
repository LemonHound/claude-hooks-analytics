import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import append_event, now_iso, read_stdin_json
from _text import normalize_text


def classify_notification(message: str) -> str:
    if not message:
        return "other"
    m = message.lower()
    if "permission" in m or "needs your approval" in m or "wants to use" in m:
        return "permission_request"
    if "waiting for your input" in m or "is waiting" in m or "idle" in m:
        return "idle_waiting"
    return "other"


def main():
    payload = read_stdin_json()
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"
    message = payload.get("message")
    if not isinstance(message, str):
        message = "" if message is None else str(message)
    normalized = normalize_text(message)

    event = {
        "phase": "notification",
        "session_id": session_id,
        "timestamp": now_iso(),
        "message": normalized[:300],
        "kind": classify_notification(normalized),
    }
    append_event(session_id, event)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
