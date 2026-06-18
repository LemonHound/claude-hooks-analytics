def _line_count(s):
    if not s:
        return 0
    return s.count("\n") + (0 if s.endswith("\n") else 1)


def compute_churn(tool_name, tool_input):
    added = 0
    removed = 0
    if not isinstance(tool_input, dict):
        return {"lines_added": 0, "lines_removed": 0}
    if tool_name == "Edit":
        removed = _line_count(tool_input.get("old_string") or "")
        added = _line_count(tool_input.get("new_string") or "")
    elif tool_name == "MultiEdit":
        for e in tool_input.get("edits") or []:
            if isinstance(e, dict):
                removed += _line_count(e.get("old_string") or "")
                added += _line_count(e.get("new_string") or "")
    elif tool_name == "Write":
        added = _line_count(tool_input.get("content") or "")
    elif tool_name == "NotebookEdit":
        added = _line_count(tool_input.get("new_source") or "")
    return {"lines_added": added, "lines_removed": removed}
