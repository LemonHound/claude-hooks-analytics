import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).parent))
from _common import append_event, read_stdin_json, now_iso, store_prompt, update_agent_map
from _churn import compute_churn
from _segments import classify_bash, classify_powershell, classify_segments, extract_mutation_targets, parse_mcp_tool
from _text import normalize_command, normalize_text


def build_event(payload: dict, now_fn: Callable[[], str] = now_iso) -> dict:
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"
    tool_name = payload.get("tool_name") or payload.get("toolName") or ""
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    tool_use_id = payload.get("tool_use_id") or payload.get("toolUseId")
    model = payload.get("model")

    is_agent_dispatch = tool_name in ("Agent", "Task")
    prompt_hash = None
    prompt_chars = None
    prompt_word_count = None
    prompt_token_estimate = None
    if is_agent_dispatch:
        raw_prompt = tool_input.get("prompt") or ""
        if raw_prompt:
            prompt_hash = store_prompt(raw_prompt)
        normalized_prompt = normalize_text(raw_prompt)
        prompt_chars = len(normalized_prompt)
        prompt_word_count = len(normalized_prompt.split())
        prompt_token_estimate = round(prompt_chars / 4)

    bash_categories = None
    powershell_categories = None
    bash_segment_categories: list = []
    bash_file_targets = None
    if tool_name == "Bash":
        cmd = normalize_command(tool_input.get("command") or "")
        bash_categories = classify_bash(cmd)
        bash_segment_categories = classify_segments(cmd, "bash")
        bash_file_targets = extract_mutation_targets(cmd, "bash")
    elif tool_name == "PowerShell":
        cmd = normalize_command(tool_input.get("command") or "")
        powershell_categories = classify_powershell(cmd)
        bash_segment_categories = classify_segments(cmd, "powershell")
        bash_file_targets = extract_mutation_targets(cmd, "powershell")

    churn = compute_churn(tool_name, tool_input)
    mcp_server, mcp_tool = parse_mcp_tool(tool_name)

    event = {
        "phase": "pre_tool",
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "tool_name": tool_name,
        "model": model,
        "tool_input_summary": _summarize_input(tool_name, tool_input),
        "cwd": payload.get("cwd"),
        "agent_type": tool_input.get("subagent_type") if is_agent_dispatch else None,
        "task_description": tool_input.get("description") if is_agent_dispatch else None,
        "task_prompt_hash": prompt_hash,
        "task_prompt_preview": (tool_input.get("prompt") or "")[:100] if is_agent_dispatch else None,
        "prompt_chars": prompt_chars,
        "prompt_word_count": prompt_word_count,
        "prompt_token_estimate": prompt_token_estimate,
        "bash_categories": bash_categories,
        "bash_segment_categories": bash_segment_categories,
        "bash_file_targets": bash_file_targets,
        "lines_added": churn["lines_added"],
        "lines_removed": churn["lines_removed"],
        "mcp_server": mcp_server,
        "mcp_tool": mcp_tool,
        "timestamp_start": now_fn(),
    }
    if tool_name == "PowerShell":
        event["powershell_categories"] = powershell_categories
    return event


def _epoch_from_now_fn(now_fn: Callable[[], str]) -> float:
    try:
        ts = now_fn()
        if not isinstance(ts, str) or not ts:
            return 0.0
        s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


def build_sidecar_entry(
    payload: dict,
    prompt_hash: str | None,
    now_fn: Callable[[], str] = now_iso,
) -> tuple[str, dict] | None:
    tool_name = payload.get("tool_name") or payload.get("toolName") or ""
    if tool_name not in ("Agent", "Task"):
        return None
    tool_use_id = payload.get("tool_use_id") or payload.get("toolUseId")
    if not tool_use_id:
        return None
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    entry = {
        "agent_type": tool_input.get("subagent_type"),
        "task_description": tool_input.get("description"),
        "prompt_hash": prompt_hash,
        "started_epoch": _epoch_from_now_fn(now_fn),
    }
    return tool_use_id, entry


def _apply_sidecar_insert(tid: str, entry: dict):
    def _fn(m: dict):
        m[tid] = entry
        return m
    return _fn


def main():
    payload = read_stdin_json()
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"
    event = build_event(payload)
    append_event(session_id, event)
    sidecar_result = build_sidecar_entry(payload, event.get("task_prompt_hash"))
    if sidecar_result is not None:
        tid, entry = sidecar_result
        try:
            update_agent_map(session_id, _apply_sidecar_insert(tid, entry))
        except Exception:
            pass


def _summarize_input(tool_name, tool_input):
    if not isinstance(tool_input, dict):
        return str(tool_input)[:200]
    keys = {
        "Read": ["file_path", "offset", "limit"],
        "Write": ["file_path"],
        "Edit": ["file_path"],
        "MultiEdit": ["file_path"],
        "NotebookEdit": ["notebook_path"],
        "Bash": ["command", "description"],
        "PowerShell": ["command", "description"],
        "Grep": ["pattern", "path"],
        "Glob": ["pattern", "path"],
        "Agent": ["description", "subagent_type", "prompt"],
        "Task": ["description", "subagent_type", "prompt"],
        "Skill": ["skill", "args"],
    }.get(tool_name, list(tool_input.keys())[:3])
    summary = {}
    for k in keys:
        if k not in tool_input:
            continue
        value = tool_input.get(k, "")
        if k == "command" and tool_name in ("Bash", "PowerShell"):
            value = normalize_command(value)
        summary[k] = str(value)[:200]
    return summary


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
