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

    event = {
        "phase": "user_prompt_submit",
        "session_id": session_id,
        "cwd": cwd,
        "timestamp": now_iso(),
        "prompt_hash": prompt_hash,
        "prompt_preview": preview,
        "prompt_char_len": char_len,
        "prompt_word_count": word_count,
        "is_correction_like": _is_correction_like(prompt_text if isinstance(prompt_text, str) else ""),
        "starts_with_slash": bool(preview and preview.startswith("/")),
    }
    append_event(session_id, event)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
