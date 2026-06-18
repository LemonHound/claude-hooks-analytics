import json
import os
import shutil
from pathlib import Path


def default_paths():
    home = Path(os.path.expanduser("~"))
    return {
        "hooks_dir": home / ".claude" / "hooks",
        "runs_dir": home / ".claude" / "runs",
        "settings_path": home / ".claude" / "settings.json",
    }


def hook_command(python, hooks_dir, script):
    p = str(python).replace("\\", "/")
    s = str(Path(hooks_dir) / script).replace("\\", "/")
    return f'"{p}" "{s}"'


def build_hook_entry(component, python, hooks_dir):
    item = {
        "type": "command",
        "command": hook_command(python, hooks_dir, component["script"]),
        "async": bool(component.get("async", False)),
    }
    if component.get("timeout") is not None:
        item["timeout"] = component["timeout"]
    entry = {"hooks": [item]}
    if component.get("matcher") is not None:
        entry["matcher"] = component["matcher"]
    return component["event"], entry


def _references_script(command, scripts):
    c = (command or "").replace("\\", "/")
    for s in scripts:
        if f"/{s}" in c or c.rstrip('"').endswith(s):
            return True
    return False


def _strip_managed(hooks_obj, managed_scripts):
    result = {}
    for event, entries in hooks_obj.items():
        new_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                new_entries.append(entry)
                continue
            original = entry.get("hooks") or []
            kept = [h for h in original if not _references_script(h.get("command", ""), managed_scripts)]
            if not original:
                new_entries.append(entry)
            elif kept:
                e = dict(entry)
                e["hooks"] = kept
                new_entries.append(e)
        if new_entries:
            result[event] = new_entries
    return result


def merge_settings(settings, selected, python, hooks_dir, managed_scripts):
    settings = dict(settings) if settings else {}
    hooks_obj = _strip_managed(dict(settings.get("hooks") or {}), managed_scripts)
    for comp in selected:
        if comp.get("kind") != "hook":
            continue
        event, entry = build_hook_entry(comp, python, hooks_dir)
        hooks_obj.setdefault(event, []).append(entry)
    settings["hooks"] = hooks_obj
    return settings
