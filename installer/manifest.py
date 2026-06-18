COMPONENTS = [
    {"id": "session_start", "label": "Session start", "description": "Records session source, cwd, model, transcript path.", "kind": "hook", "default_enabled": True, "event": "SessionStart", "matcher": None, "async": True, "timeout": None, "script": "session_start.py"},
    {"id": "user_prompt", "label": "User prompts", "description": "Captures prompt size, preview, and course-correction signal.", "kind": "hook", "default_enabled": True, "event": "UserPromptSubmit", "matcher": None, "async": True, "timeout": None, "script": "user_prompt.py"},
    {"id": "pre_tool", "label": "Pre-tool", "description": "Logs every tool call, agent dispatches, and bash classification.", "kind": "hook", "default_enabled": True, "event": "PreToolUse", "matcher": ".*", "async": False, "timeout": None, "script": "pre_tool.py"},
    {"id": "post_tool", "label": "Post-tool", "description": "Logs tool results, errors, web/search metadata, and denials.", "kind": "hook", "default_enabled": True, "event": "PostToolUse", "matcher": ".*", "async": True, "timeout": None, "script": "post_tool.py"},
    {"id": "post_edit_check", "label": "Edit conflict check", "description": "Blocks when conflict markers remain after an edit.", "kind": "hook", "default_enabled": True, "event": "PostToolUse", "matcher": "Edit|Write|MultiEdit|NotebookEdit", "async": False, "timeout": None, "script": "post_edit_check.py"},
    {"id": "subagent_stop", "label": "Subagent rollup", "description": "Writes a per-subagent artifact with tokens and outcome.", "kind": "hook", "default_enabled": True, "event": "SubagentStop", "matcher": None, "async": True, "timeout": None, "script": "subagent_stop.py"},
    {"id": "session_end", "label": "Session rollup", "description": "Writes the session summary, turns, ship signals, and timing.", "kind": "hook", "default_enabled": True, "event": "Stop", "matcher": None, "async": True, "timeout": None, "script": "session_end.py"},
    {"id": "record_subagent_feedback", "label": "Subagent feedback CLI", "description": "Lets the feedback skill attach outcome data. Copied; no hook entry.", "kind": "support", "default_enabled": True, "script": "record_subagent_feedback.py"},
    {"id": "analyze", "label": "Text report", "description": "Terminal analytics report. Runs from the repo.", "kind": "tool", "default_enabled": False, "path": "analytics/analyze.py"},
    {"id": "dashboard", "label": "Browser dashboard", "description": "Self-contained HTML dashboard. Runs from the repo.", "kind": "tool", "default_enabled": False, "path": "analytics/dashboard.py"},
]


def managed_scripts():
    return [c["script"] for c in COMPONENTS if c.get("script")]
