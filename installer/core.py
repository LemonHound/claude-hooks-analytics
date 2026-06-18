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
