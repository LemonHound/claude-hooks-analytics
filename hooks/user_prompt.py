import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import append_event, now_iso, read_stdin_json, store_prompt


CORRECTION_CUES = (
    "no,", "no.", "no ",
    "don't", "do not",
    "stop ", "stop,", "stop.",
    "that's wrong", "that is wrong",
    "you were supposed", "i said", "i told you", "that's not what",
    "rollback", "revert", "undo",
    "retry", "redo", "scrap",
)


CROSS_SESSION_FROM_PATTERN = re.compile(r'<cross-session-message from="([^"]+)"')

APP_EVENT_TAGS = (
    ("<ci-monitor-event>", "ci_monitor"),
    ("<side-sessions-event>", "side_sessions"),
    ("<task-notification>", "task_notification"),
)


def get_prompt_source(text: str) -> tuple[str, str | None]:
    cross_session_match = CROSS_SESSION_FROM_PATTERN.search(text)
    if cross_session_match is not None:
        return "cross_session", cross_session_match.group(1)
    for tag, source in APP_EVENT_TAGS:
        if tag in text:
            return source, None
    return "user", None


def _is_correction_like(text: str) -> bool:
    if not text:
        return False
    head = text.strip().lower()[:160]
    return any(cue in head for cue in CORRECTION_CUES)


def main():
    payload = read_stdin_json()
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"
    prompt_text = payload.get("prompt") or payload.get("user_prompt") or ""
    cwd = payload.get("cwd")

    prompt_hash = None
    char_len = 0
    word_count = 0
    if isinstance(prompt_text, str) and prompt_text.strip():
        prompt_hash = store_prompt(prompt_text)
        char_len = len(prompt_text)
        word_count = len(prompt_text.split())

    preview = ""
    if isinstance(prompt_text, str):
        preview = prompt_text.strip().replace("\n", " ")[:200]

    prompt_source = "user"
    from_session_id = None
    if isinstance(prompt_text, str):
        prompt_source, from_session_id = get_prompt_source(prompt_text)
    is_user_prompt = prompt_source == "user"

    event = {
        "phase": "user_prompt_submit",
        "session_id": session_id,
        "cwd": cwd,
        "timestamp": now_iso(),
        "prompt_hash": prompt_hash,
        "prompt_preview": preview,
        "prompt_char_len": char_len,
        "prompt_word_count": word_count,
        "prompt_source": prompt_source,
        "from_session_id": from_session_id,
        "is_correction_like": is_user_prompt and _is_correction_like(prompt_text if isinstance(prompt_text, str) else ""),
        "starts_with_slash": bool(is_user_prompt and preview.startswith("/")),
    }
    append_event(session_id, event)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        from _common import record_hook_error
        record_hook_error(__file__)
    sys.exit(0)
