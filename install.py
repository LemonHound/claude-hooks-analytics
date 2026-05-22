#!/usr/bin/env python3
"""
Cross-platform installer for Claude Code telemetry hooks.

Usage:
  Windows:  python install.py
  Mac/Linux: python3 install.py

What it does:
  1. Creates ~/.claude/runs/{events,sessions,prompts} directories
  2. Creates a .venv in this hooks directory if missing
  3. Merges hook definitions into ~/.claude/settings.json
  4. Prints next steps (setting CLAUDE_SESSION_TAG)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.resolve()
CLAUDE_DIR = Path.home() / ".claude"
SETTINGS_PATH = CLAUDE_DIR / "settings.json"
RUNS_DIRS = [
    CLAUDE_DIR / "runs",
    CLAUDE_DIR / "runs" / "events",
    CLAUDE_DIR / "runs" / "sessions",
    CLAUDE_DIR / "runs" / "prompts",
]

IS_WINDOWS = sys.platform == "win32"


def _python_cmd() -> str:
    venv = HOOKS_DIR / ".venv"
    if IS_WINDOWS:
        candidate = venv / "Scripts" / "python.exe"
    else:
        candidate = venv / "bin" / "python3"
    if candidate.exists():
        return str(candidate).replace("\\", "/")
    return "python3" if not IS_WINDOWS else "python"


def _hook_cmd(script: str, python: str) -> str:
    return f'{python} "$HOME/.claude/hooks/{script}"'


def _build_hook_entries(python: str) -> dict:
    def _async(script):
        return {"type": "command", "command": _hook_cmd(script, python), "async": True}

    def _sync(script):
        return {"type": "command", "command": _hook_cmd(script, python), "async": False}

    return {
        "SessionStart": [{"hooks": [_async("session_start.py")]}],
        "UserPromptSubmit": [{"hooks": [_async("user_prompt.py")]}],
        "PreToolUse": [{"matcher": ".*", "hooks": [_sync("pre_tool.py")]}],
        "PostToolUse": [
            {"matcher": ".*", "hooks": [_async("post_tool.py")]},
            {"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [_sync("post_edit_check.py")]},
        ],
        "SubagentStop": [{"hooks": [_async("subagent_stop.py")]}],
        "Stop": [{"hooks": [_async("session_end.py")]}],
    }


def _setup_dirs():
    for d in RUNS_DIRS:
        d.mkdir(parents=True, exist_ok=True)
        print(f"  ok  {d}")


def _setup_venv():
    venv = HOOKS_DIR / ".venv"
    if venv.exists():
        print(f"  ok  .venv already exists at {venv}")
        return
    print(f"  creating .venv at {venv} ...")
    subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
    print(f"  ok  .venv created")


def _merge_settings(hook_entries: dict):
    settings: dict = {}
    if SETTINGS_PATH.exists():
        try:
            settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  WARN  could not parse {SETTINGS_PATH}: {e}")
            settings = {}

    existing_hooks = settings.setdefault("hooks", {})
    changed = False

    for event, new_entries in hook_entries.items():
        existing = existing_hooks.get(event, [])
        existing_cmds = {
            h.get("command")
            for entry in existing
            for h in (entry.get("hooks") or [])
        }
        for entry in new_entries:
            for h in entry.get("hooks") or []:
                if h.get("command") not in existing_cmds:
                    existing_hooks.setdefault(event, []).append(entry)
                    changed = True
                    print(f"  added  {event}: {h['command'][:60]}")
                    break

    if not changed:
        print("  ok  all hook entries already present in settings.json")
        return

    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_PATH)
    print(f"  ok  {SETTINGS_PATH} updated")


def main():
    print("\n=== Claude Hooks Installer ===\n")
    print(f"Platform:   {'Windows' if IS_WINDOWS else 'Mac/Linux'}")
    print(f"Hooks dir:  {HOOKS_DIR}")
    print(f"Claude dir: {CLAUDE_DIR}\n")

    print("1. Creating run directories...")
    _setup_dirs()
    print()

    print("2. Setting up Python virtual environment...")
    _setup_venv()
    print()

    python = _python_cmd()
    print(f"3. Using Python: {python}")
    hook_entries = _build_hook_entries(python)
    print()

    print("4. Merging hook entries into settings.json...")
    _merge_settings(hook_entries)
    print()

    print("=== Done ===\n")
    print("To tag sessions by account (personal vs work), set CLAUDE_SESSION_TAG")
    print("in your shell profile before launching Claude Code:\n")
    if IS_WINDOWS:
        print("  PowerShell profile:  $env:CLAUDE_SESSION_TAG = 'work'")
        print("  Or set permanently:  [System.Environment]::SetEnvironmentVariable('CLAUDE_SESSION_TAG','work','User')")
    else:
        print("  ~/.zshrc or ~/.bashrc:  export CLAUDE_SESSION_TAG=work")
    print()
    print("To run analysis (text):")
    print(f"  python{'3' if not IS_WINDOWS else ''} {HOOKS_DIR / 'analyze.py'} [--days 30]")
    print()
    print("To launch the browser dashboard:")
    print(f"  python{'3' if not IS_WINDOWS else ''} {HOOKS_DIR / 'dashboard.py'} [--days 30]")


if __name__ == "__main__":
    main()
