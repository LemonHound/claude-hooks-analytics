import json
import re
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).parent))
from _common import append_event, read_stdin_json, now_iso
from _segments import classify_bash, classify_powershell
from _testparse import parse_test_output
from _text import normalize_text


URL_MAX_CHARS = 2048
QUERY_MAX_CHARS = 1024

_URL_FIELD_DROP_TABLE = str.maketrans("", "", "\n\t")


def _strip_userinfo(url: str | None) -> str | None:
    if not isinstance(url, str) or "@" not in url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.username and not parts.password:
        return url
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _scrub_field(s: str) -> str:
    return normalize_text(s).translate(_URL_FIELD_DROP_TABLE)


def _concat_content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                parts.append(str(item))
        return "".join(parts)
    return ""


def _get_shell_output_text(tool_response) -> str:
    if not isinstance(tool_response, dict):
        return ""
    stdout = tool_response.get("stdout")
    if not isinstance(stdout, str):
        stdout = ""
    stderr = tool_response.get("stderr")
    if not isinstance(stderr, str):
        stderr = ""
    return stdout + "\n" + stderr


def _parse_host(url):
    if not url or not isinstance(url, str):
        return None
    try:
        return urlparse(url).hostname
    except ValueError:
        return None


def _extract_loaded_tool_names(text: str) -> list[str]:
    if not text:
        return []
    names: set[str] = set()
    cursor = 0
    needle = '"name":'
    while True:
        idx = text.find(needle, cursor)
        if idx == -1:
            break
        cursor = idx + len(needle)
        rest = text[cursor:cursor + 200]
        q1 = rest.find('"')
        if q1 == -1:
            continue
        q2 = rest.find('"', q1 + 1)
        if q2 == -1:
            continue
        name = rest[q1 + 1:q2]
        if name:
            names.add(name)
    return sorted(names)


START_SESSION_TOOL_NAME = "mcp__ccd_session__start_session"

STARTED_SESSION_ID_PATTERN = re.compile(r"session_id: (local_[0-9a-f-]+)")

PROPOSED_TASK_ID_PATTERN = re.compile(r"task_id: (task_[0-9a-f]+)")


def get_started_session_ids(tool_response) -> tuple[str | None, str | None]:
    response_text = json.dumps(tool_response, default=str)
    started_match = STARTED_SESSION_ID_PATTERN.search(response_text)
    proposed_match = PROPOSED_TASK_ID_PATTERN.search(response_text)
    started_session_id = started_match.group(1) if started_match else None
    proposed_task_id = proposed_match.group(1) if proposed_match else None
    return started_session_id, proposed_task_id


def build_event(
    payload: dict,
    now_fn: Callable[[], str] = now_iso,
) -> dict:
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"
    tool_name = payload.get("tool_name") or payload.get("toolName") or ""
    tool_use_id = payload.get("tool_use_id") or payload.get("toolUseId")
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    tool_response = payload.get("tool_response") or payload.get("toolResponse") or {}
    model = payload.get("model")

    usage = {}
    if isinstance(tool_response, dict):
        usage = tool_response.get("usage") or tool_response.get("totalUsage") or {}

    input_tok = usage.get("input_tokens") or usage.get("inputTokens")
    output_tok = usage.get("output_tokens") or usage.get("outputTokens")
    cache_read = usage.get("cache_read_input_tokens") or usage.get("cacheReadInputTokens")
    cache_creation = usage.get("cache_creation_input_tokens") or usage.get("cacheCreationInputTokens")

    is_failure = payload.get("hook_event_name") == "PostToolUseFailure"
    failure_error_text = str(payload.get("error") or "")

    is_error = bool(tool_response.get("is_error")) if isinstance(tool_response, dict) else False
    error_message = None
    if is_failure:
        is_error = True
        error_message = failure_error_text[:500] or None
    elif is_error and isinstance(tool_response, dict):
        content = tool_response.get("content") or ""
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        error_message = str(content)[:500] or None

    raw_content = tool_response.get("content") if isinstance(tool_response, dict) else None

    response_char_len = None
    request_url = None
    request_host = None
    request_url_truncated = None
    query = None
    query_truncated = None
    result_count = None
    toolsearch_tools_loaded = None

    if tool_name == "WebFetch":
        text = normalize_text(_concat_content_text(raw_content))
        response_char_len = len(text)
        url = tool_input.get("url") if isinstance(tool_input, dict) else None
        if isinstance(url, str):
            normalized = _scrub_field(_strip_userinfo(url))
            if len(normalized) > URL_MAX_CHARS:
                request_url = normalized[:URL_MAX_CHARS]
                request_url_truncated = True
            else:
                request_url = normalized
                request_url_truncated = False
        else:
            request_url_truncated = False
        request_host = _parse_host(request_url)
    elif tool_name == "WebSearch":
        query_val = tool_input.get("query") if isinstance(tool_input, dict) else None
        if isinstance(query_val, str):
            normalized_q = _scrub_field(query_val)
            if len(normalized_q) > QUERY_MAX_CHARS:
                query = normalized_q[:QUERY_MAX_CHARS]
                query_truncated = True
            else:
                query = normalized_q
                query_truncated = False
        else:
            query = None
            query_truncated = False
        if isinstance(raw_content, list):
            result_count = len(raw_content)
            parts = []
            for item in raw_content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                else:
                    parts.append(str(item))
            text = normalize_text("".join(parts))
            response_char_len = len(text)
        else:
            result_count = None
            response_char_len = len(normalize_text(_concat_content_text(raw_content)))
    elif tool_name == "ToolSearch":
        text = _concat_content_text(raw_content)
        toolsearch_tools_loaded = _extract_loaded_tool_names(text)

    test_info = None
    if tool_name in ("Bash", "PowerShell") and isinstance(tool_input, dict):
        cmd = tool_input.get("command") or ""
        cats = classify_bash(cmd) if tool_name == "Bash" else classify_powershell(cmd)
        if "test" in cats:
            if is_failure:
                test_output = failure_error_text
            else:
                test_output = _get_shell_output_text(tool_response)
            test_info = parse_test_output(normalize_text(test_output), is_error)

    started_session_id = None
    proposed_task_id = None
    if tool_name == START_SESSION_TOOL_NAME:
        started_session_id, proposed_task_id = get_started_session_ids(tool_response)

    event = {
        "phase": "post_tool",
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "tool_name": tool_name,
        "started_session_id": started_session_id,
        "proposed_task_id": proposed_task_id,
        "model": model,
        "timestamp_end": now_fn(),
        "input_tokens": input_tok,
        "output_tokens": output_tok,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_creation,
        "stop_reason": tool_response.get("stop_reason") if isinstance(tool_response, dict) else None,
        "is_error": is_error,
        "error_message": error_message,
        "response_char_len": response_char_len,
        "request_url": request_url,
        "request_host": request_host,
        "request_url_truncated": request_url_truncated,
        "query": query,
        "query_truncated": query_truncated,
        "result_count": result_count,
        "toolsearch_tools_loaded": toolsearch_tools_loaded,
        "test": test_info,
    }

    return event


def main():
    payload = read_stdin_json()
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"
    event = build_event(payload)
    append_event(session_id, event)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        from _common import record_hook_error
        record_hook_error(__file__)
    sys.exit(0)
