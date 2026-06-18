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


def shared_modules(src_hooks_dir):
    return sorted(p.name for p in Path(src_hooks_dir).glob("_*.py"))


def copy_components(selected, src_hooks_dir, dest_hooks_dir):
    src = Path(src_hooks_dir)
    dest = Path(dest_hooks_dir)
    dest.mkdir(parents=True, exist_ok=True)
    for comp in selected:
        if comp.get("kind") not in ("hook", "support"):
            continue
        script = comp.get("script")
        if script:
            shutil.copy2(src / script, dest / script)
    for name in shared_modules(src):
        shutil.copy2(src / name, dest / name)


def write_install_config(hooks_dir, runs_dir):
    path = Path(hooks_dir) / "installer_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"runs_dir": str(runs_dir)}, indent=2), encoding="utf-8")
    return path


def create_runs_dirs(runs_dir):
    base = Path(runs_dir)
    for sub in ("", "events", "sessions", "prompts"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def read_settings(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_settings(path, settings):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p


def install(selected, hooks_dir, runs_dir, settings_path, python, src_hooks_dir, managed):
    copy_components(selected, src_hooks_dir, hooks_dir)
    write_install_config(hooks_dir, runs_dir)
    create_runs_dirs(runs_dir)
    settings = read_settings(settings_path)
    merged = merge_settings(settings, selected, python, hooks_dir, managed)
    write_settings(settings_path, merged)
    return merged


def analytics_command(python, repo_root, tool, runs_dir, output_path=None):
    script = Path(repo_root) / "analytics" / f"{tool}.py"
    cmd = [str(python), str(script), "--runs-dir", str(runs_dir)]
    if output_path is not None:
        cmd += ["--output", str(output_path)]
    return cmd
