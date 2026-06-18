# Installer + Repo Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the flat repo into `hooks/ analytics/ installer/`, add custom-path support to the hooks and analyzers, and ship a stdlib-only Tkinter installer launched by one entry script per OS.

**Architecture:** Hooks plus their shared `_*.py` modules live together in `hooks/` (copied flat to the install dir). A manifest-driven installer package (`installer/`) has a pure-logic core (`core.py`), a declarative `manifest.py`, and a thin Tkinter UI. Entry scripts (`install.sh`, `install.cmd`) only locate Python and run `python -m installer`. Custom data dir is honored via an install-written `installer_config.json` the hooks read relative to themselves, and via `--runs-dir`/env for the analyzers.

**Tech Stack:** Python 3.12+ stdlib only (Tkinter, json, shutil, pathlib). Tests use stdlib `unittest`. No third-party dependencies.

**How to run tests (from repo root):**
```
python -m unittest discover -s tests -t .
```

---

### Task 1: Restructure folders

**Files:**
- Move into `hooks/`: `session_start.py user_prompt.py pre_tool.py post_tool.py post_edit_check.py subagent_stop.py session_end.py record_subagent_feedback.py _common.py _config.py _segments.py _text.py _transcript.py`
- Move into `analytics/`: `analyze.py dashboard.py`
- Delete: `install.py`
- Create: `installer/__init__.py` (empty), `tests/__init__.py` (empty)

- [ ] **Step 1: Create target dirs and move files**

Run:
```bash
mkdir -p hooks analytics installer tests
git mv session_start.py user_prompt.py pre_tool.py post_tool.py post_edit_check.py subagent_stop.py session_end.py record_subagent_feedback.py _common.py _config.py _segments.py _text.py _transcript.py hooks/
git mv analyze.py dashboard.py analytics/
git rm install.py
```

- [ ] **Step 2: Create empty package markers**

Create `installer/__init__.py` with no content. Create `tests/__init__.py` with no content.

- [ ] **Step 3: Smoke-test that hook imports still resolve**

Run:
```bash
python -c "import sys; sys.path.insert(0,'hooks'); import _common,_config,_segments,_text,_transcript,session_start,user_prompt,pre_tool,post_tool,post_edit_check,subagent_stop,session_end; print('ok')"
```
Expected: prints `ok` (the `from _common import ...` lines resolve because the modules are co-located).

- [ ] **Step 4: Smoke-test analyzers import**

Run:
```bash
python -c "import sys; sys.path.insert(0,'analytics'); import analyze,dashboard; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Restructure into hooks/, analytics/, installer/"
```

---

### Task 2: Custom data-dir resolution in `_common.py`

**Files:**
- Modify: `hooks/_common.py` (lines 13-20, the `RUNS_DIR` block)
- Test: `tests/test_common_paths.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_common_paths.py`:
```python
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import _common


class CommonPathResolution(unittest.TestCase):
    def test_env_var_wins(self):
        d = _common.resolve_runs_dir(env={"CLAUDE_HOOKS_RUNS_DIR": "/tmp/foo"}, config_path="/does/not/exist")
        self.assertEqual(d, Path(os.path.expanduser("/tmp/foo")))

    def test_config_file_used_when_no_env(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "installer_config.json"
            cfg.write_text(json.dumps({"runs_dir": "/data/runs"}), encoding="utf-8")
            d = _common.resolve_runs_dir(env={}, config_path=str(cfg))
            self.assertEqual(d, Path(os.path.expanduser("/data/runs")))

    def test_default_when_nothing_set(self):
        d = _common.resolve_runs_dir(env={}, config_path="/nope/installer_config.json")
        self.assertEqual(d, Path(os.path.expanduser("~/.claude/runs")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_common_paths -v`
Expected: FAIL with `AttributeError: module '_common' has no attribute 'resolve_runs_dir'`.

- [ ] **Step 3: Implement the resolver**

In `hooks/_common.py`, replace this block:
```python
RUNS_DIR = Path(os.path.expanduser("~/.claude/runs"))
EVENTS_DIR = RUNS_DIR / "events"
ARTIFACTS_DIR = RUNS_DIR
SESSIONS_DIR = RUNS_DIR / "sessions"
PROMPTS_DIR = RUNS_DIR / "prompts"

for d in (RUNS_DIR, EVENTS_DIR, SESSIONS_DIR, PROMPTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
```
with:
```python
def resolve_runs_dir(env=None, config_path=None):
    env = env if env is not None else os.environ
    val = env.get("CLAUDE_HOOKS_RUNS_DIR")
    if val:
        return Path(os.path.expanduser(val))
    cfg = Path(config_path) if config_path is not None else (Path(__file__).resolve().parent / "installer_config.json")
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        rd = data.get("runs_dir")
        if rd:
            return Path(os.path.expanduser(rd))
    except Exception:
        pass
    return Path(os.path.expanduser("~/.claude/runs"))


RUNS_DIR = resolve_runs_dir()
EVENTS_DIR = RUNS_DIR / "events"
ARTIFACTS_DIR = RUNS_DIR
SESSIONS_DIR = RUNS_DIR / "sessions"
PROMPTS_DIR = RUNS_DIR / "prompts"

for d in (RUNS_DIR, EVENTS_DIR, SESSIONS_DIR, PROMPTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
```
(`json` and `os` are already imported at the top of the file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_common_paths -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add hooks/_common.py tests/test_common_paths.py
git commit -m "Resolve hook data dir from env or install config"
```

---

### Task 3: Custom data-dir resolution in the analyzers

**Files:**
- Modify: `analytics/analyze.py` (add `import os`, add `_resolve_runs_dir`, update `main`)
- Modify: `analytics/dashboard.py` (add `_resolve_runs_dir`, update `main`)
- Test: `tests/test_analytics_paths.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_analytics_paths.py`:
```python
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analytics"))
import analyze
import dashboard


class AnalyticsPathResolution(unittest.TestCase):
    def test_override_wins(self):
        self.assertEqual(analyze._resolve_runs_dir(override="/x", env={}, config_path="/none"), Path("/x"))
        self.assertEqual(dashboard._resolve_runs_dir(override="/x", env={}, config_path="/none"), Path("/x"))

    def test_env_used(self):
        self.assertEqual(
            analyze._resolve_runs_dir(override=None, env={"CLAUDE_HOOKS_RUNS_DIR": "/y"}, config_path="/none"),
            Path(os.path.expanduser("/y")),
        )

    def test_config_used(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "installer_config.json"
            cfg.write_text(json.dumps({"runs_dir": "/data/runs"}), encoding="utf-8")
            self.assertEqual(
                dashboard._resolve_runs_dir(override=None, env={}, config_path=str(cfg)),
                Path(os.path.expanduser("/data/runs")),
            )

    def test_default(self):
        self.assertEqual(
            analyze._resolve_runs_dir(override=None, env={}, config_path="/none"),
            Path.home() / ".claude" / "runs",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_analytics_paths -v`
Expected: FAIL with `AttributeError: module 'analyze' has no attribute '_resolve_runs_dir'`.

- [ ] **Step 3: Implement in `analytics/analyze.py`**

Add `import os` to the imports at the top. After the `RUNS_DIR`/`SESSIONS_DIR` module assignments (near line 10-11), add:
```python
def _resolve_runs_dir(override=None, env=None, config_path=None):
    if override:
        return Path(override)
    env = env if env is not None else os.environ
    val = env.get("CLAUDE_HOOKS_RUNS_DIR")
    if val:
        return Path(os.path.expanduser(val))
    cfg = Path(config_path) if config_path is not None else Path(os.path.expanduser("~/.claude/hooks/installer_config.json"))
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        rd = data.get("runs_dir")
        if rd:
            return Path(os.path.expanduser(rd))
    except Exception:
        pass
    return Path.home() / ".claude" / "runs"
```
In `main`, replace:
```python
    global RUNS_DIR, SESSIONS_DIR
    if args.runs_dir:
        RUNS_DIR = Path(args.runs_dir)
        SESSIONS_DIR = RUNS_DIR / "sessions"
```
with:
```python
    global RUNS_DIR, SESSIONS_DIR
    RUNS_DIR = _resolve_runs_dir(args.runs_dir)
    SESSIONS_DIR = RUNS_DIR / "sessions"
```

- [ ] **Step 4: Implement in `analytics/dashboard.py`**

(`os` and `json` are already imported.) After the `RUNS_DIR`/`SESSIONS_DIR` module assignments (near line 13-14), add the same function:
```python
def _resolve_runs_dir(override=None, env=None, config_path=None):
    if override:
        return Path(override)
    env = env if env is not None else os.environ
    val = env.get("CLAUDE_HOOKS_RUNS_DIR")
    if val:
        return Path(os.path.expanduser(val))
    cfg = Path(config_path) if config_path is not None else Path(os.path.expanduser("~/.claude/hooks/installer_config.json"))
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        rd = data.get("runs_dir")
        if rd:
            return Path(os.path.expanduser(rd))
    except Exception:
        pass
    return Path.home() / ".claude" / "runs"
```
In `main`, replace:
```python
    runs_dir = Path(args.runs_dir) if args.runs_dir else RUNS_DIR
```
with:
```python
    runs_dir = _resolve_runs_dir(args.runs_dir)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m unittest tests.test_analytics_paths -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add analytics/analyze.py analytics/dashboard.py tests/test_analytics_paths.py
git commit -m "Resolve analyzer data dir from arg, env, or install config"
```

---

### Task 4: `installer/manifest.py`

**Files:**
- Create: `installer/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_manifest.py`:
```python
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from installer.manifest import COMPONENTS, managed_scripts


class Manifest(unittest.TestCase):
    def test_hook_components_have_required_keys(self):
        for c in COMPONENTS:
            if c["kind"] == "hook":
                for k in ("id", "label", "description", "event", "script"):
                    self.assertIn(k, c, f"{c.get('id')} missing {k}")

    def test_all_referenced_scripts_exist(self):
        for c in COMPONENTS:
            script = c.get("script")
            if script:
                self.assertTrue((REPO / "hooks" / script).exists(), script)

    def test_tool_paths_exist(self):
        for c in COMPONENTS:
            if c["kind"] == "tool":
                self.assertTrue((REPO / c["path"]).exists(), c["path"])

    def test_managed_scripts_lists_every_hook_and_support(self):
        expected = {c["script"] for c in COMPONENTS if c.get("script")}
        self.assertEqual(set(managed_scripts()), expected)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_manifest -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'installer.manifest'`.

- [ ] **Step 3: Implement `installer/manifest.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_manifest -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add installer/manifest.py tests/test_manifest.py
git commit -m "Add installer component manifest"
```

---

### Task 5: `installer/core.py` — commands and hook entries

**Files:**
- Create: `installer/core.py`
- Test: `tests/test_core_entries.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_core_entries.py`:
```python
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from installer import core


class CoreEntries(unittest.TestCase):
    def test_default_paths(self):
        p = core.default_paths()
        self.assertEqual(p["settings_path"], Path(os.path.expanduser("~")) / ".claude" / "settings.json")

    def test_hook_command_uses_forward_slashes_and_quotes(self):
        cmd = core.hook_command("C:\\Py\\python.exe", "C:\\h", "pre_tool.py")
        self.assertEqual(cmd, '"C:/Py/python.exe" "C:/h/pre_tool.py"')

    def test_build_entry_with_matcher(self):
        comp = {"event": "PreToolUse", "matcher": ".*", "async": False, "script": "pre_tool.py", "kind": "hook", "timeout": None}
        event, entry = core.build_hook_entry(comp, "py", "/h")
        self.assertEqual(event, "PreToolUse")
        self.assertEqual(entry["matcher"], ".*")
        self.assertIs(entry["hooks"][0]["async"], False)
        self.assertEqual(entry["hooks"][0]["command"], '"py" "/h/pre_tool.py"')

    def test_build_entry_without_matcher_omits_key(self):
        comp = {"event": "SessionStart", "matcher": None, "async": True, "script": "session_start.py", "kind": "hook", "timeout": None}
        event, entry = core.build_hook_entry(comp, "py", "/h")
        self.assertNotIn("matcher", entry)
        self.assertIs(entry["hooks"][0]["async"], True)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_core_entries -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'installer.core'`.

- [ ] **Step 3: Implement the first part of `installer/core.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_core_entries -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add installer/core.py tests/test_core_entries.py
git commit -m "Add installer core paths and hook entry builders"
```

---

### Task 6: `installer/core.py` — non-destructive settings merge

**Files:**
- Modify: `installer/core.py` (append merge functions)
- Test: `tests/test_core_merge.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_core_merge.py`:
```python
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from installer import core

SESSION_START = {"event": "SessionStart", "matcher": None, "async": True, "script": "session_start.py", "kind": "hook", "timeout": None}
SESSION_END = {"event": "Stop", "matcher": None, "async": True, "script": "session_end.py", "kind": "hook", "timeout": None}
MANAGED = ["session_start.py", "session_end.py", "pre_tool.py"]


class CoreMerge(unittest.TestCase):
    def test_preserves_non_hook_settings(self):
        settings = {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {}}
        out = core.merge_settings(settings, [SESSION_START], "py", "/new/hooks", MANAGED)
        self.assertEqual(out["permissions"], {"allow": ["Bash(ls)"]})

    def test_preserves_foreign_hooks(self):
        settings = {"hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": "python /other/foreign.py", "async": False}]}]}}
        out = core.merge_settings(settings, [SESSION_START], "py", "/new/hooks", MANAGED)
        cmds = [h["command"] for e in out["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertIn("python /other/foreign.py", cmds)

    def test_replaces_stale_entry_for_relocated_hook(self):
        settings = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": '"py" "/old/hooks/session_start.py"', "async": True}]}]}}
        out = core.merge_settings(settings, [SESSION_START], "py", "/new/hooks", MANAGED)
        cmds = [h["command"] for e in out["hooks"]["SessionStart"] for h in e["hooks"]]
        self.assertEqual(len(cmds), 1)
        self.assertIn("/new/hooks/session_start.py", cmds[0])
        self.assertNotIn("/old/hooks", cmds[0])

    def test_removes_deselected_component(self):
        settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": '"py" "/h/session_end.py"', "async": True}]}]}}
        out = core.merge_settings(settings, [], "py", "/h", MANAGED)
        self.assertNotIn("Stop", out["hooks"])

    def test_adds_selected_when_absent(self):
        out = core.merge_settings({}, [SESSION_END], "py", "/h", MANAGED)
        cmds = [h["command"] for e in out["hooks"]["Stop"] for h in e["hooks"]]
        self.assertEqual(cmds, ['"py" "/h/session_end.py"'])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_core_merge -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'merge_settings'`.

- [ ] **Step 3: Append merge logic to `installer/core.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_core_merge -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add installer/core.py tests/test_core_merge.py
git commit -m "Add non-destructive settings merge"
```

---

### Task 7: `installer/core.py` — copy, config, dirs, and install orchestration

**Files:**
- Modify: `installer/core.py` (append remaining functions)
- Test: `tests/test_core_install.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_core_install.py`:
```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from installer import core
from installer.manifest import COMPONENTS, managed_scripts

SRC_HOOKS = REPO / "hooks"


def _by_id(*ids):
    return [c for c in COMPONENTS if c["id"] in ids]


class CoreInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.hooks = self.base / "hooks"
        self.runs = self.base / "runs"
        self.settings = self.base / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_copies_scripts_shared_and_support(self):
        core.install(_by_id("session_start", "record_subagent_feedback"), self.hooks, self.runs, self.settings, "py", SRC_HOOKS, managed_scripts())
        self.assertTrue((self.hooks / "session_start.py").exists())
        self.assertTrue((self.hooks / "_common.py").exists())
        self.assertTrue((self.hooks / "record_subagent_feedback.py").exists())

    def test_install_writes_config_and_dirs(self):
        core.install(_by_id("session_start"), self.hooks, self.runs, self.settings, "py", SRC_HOOKS, managed_scripts())
        cfg = json.loads((self.hooks / "installer_config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["runs_dir"], str(self.runs))
        self.assertTrue((self.runs / "events").is_dir())
        self.assertTrue((self.runs / "sessions").is_dir())
        self.assertTrue((self.runs / "prompts").is_dir())

    def test_install_merges_into_existing_settings(self):
        self.settings.write_text(json.dumps({"permissions": {"x": 1}}), encoding="utf-8")
        core.install(_by_id("session_start"), self.hooks, self.runs, self.settings, "py", SRC_HOOKS, managed_scripts())
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(data["permissions"], {"x": 1})
        self.assertIn("SessionStart", data["hooks"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_core_install -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'install'`.

- [ ] **Step 3: Append the remaining functions to `installer/core.py`**

```python
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
```
Note: `create_runs_dirs` uses `base / ""` which equals `base`, so the root dir is created too.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_core_install -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite**

Run: `python -m unittest discover -s tests -t . -v`
Expected: PASS (all tests from Tasks 2-7).

- [ ] **Step 6: Commit**

```bash
git add installer/core.py tests/test_core_install.py
git commit -m "Add installer copy, config, and orchestration"
```

---

### Task 8: Tkinter UI (`theme.py`, `ui.py`, `__main__.py`)

**Files:**
- Create: `installer/theme.py`
- Create: `installer/ui.py`
- Create: `installer/__main__.py`
- Test: `tests/test_ui_import.py`

- [ ] **Step 1: Write the failing import-smoke test**

Create `tests/test_ui_import.py`:
```python
import importlib
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


class UiImports(unittest.TestCase):
    def test_theme_and_ui_import(self):
        try:
            import tkinter
        except Exception:
            self.skipTest("tkinter not available")
        del tkinter
        theme = importlib.import_module("installer.theme")
        ui = importlib.import_module("installer.ui")
        self.assertTrue(hasattr(theme, "apply_theme"))
        self.assertTrue(hasattr(ui, "run"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_ui_import -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'installer.theme'`.

- [ ] **Step 3: Implement `installer/theme.py`**

```python
from tkinter import ttk

BG = "#1e1f22"
PANEL = "#2b2d31"
FG = "#e6e6e6"
MUTED = "#9aa0a6"
ACCENT = "#3b82f6"


def apply_theme(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(".", background=BG, foreground=FG, fieldbackground=PANEL)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure("Heading.TLabel", background=BG, foreground=FG, font=("", 12, "bold"))
    style.configure("TButton", background=PANEL, foreground=FG)
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
    style.configure("TCheckbutton", background=BG, foreground=FG)
    style.configure("TEntry", fieldbackground=PANEL, foreground=FG)
    style.map("TButton", background=[("active", ACCENT)])
    style.map("TCheckbutton", background=[("active", BG)])
```

- [ ] **Step 4: Implement `installer/ui.py`**

```python
import sys
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, Text, filedialog, ttk, END, DISABLED, NORMAL, W

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from installer import core
from installer.manifest import COMPONENTS, managed_scripts
from installer.theme import apply_theme

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_HOOKS = REPO_ROOT / "hooks"


def _browse_dir(var):
    chosen = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
    if chosen:
        var.set(chosen)


def _browse_file(var):
    chosen = filedialog.askopenfilename(initialfile=var.get())
    if chosen:
        var.set(chosen)


def run():
    defaults = core.default_paths()
    root = Tk()
    root.title("Claude Hooks Analytics Installer")
    root.geometry("780x680")
    apply_theme(root)

    hooks_var = StringVar(value=str(defaults["hooks_dir"]))
    runs_var = StringVar(value=str(defaults["runs_dir"]))
    settings_var = StringVar(value=str(defaults["settings_path"]))

    frm = ttk.Frame(root, padding=16)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Install locations", style="Heading.TLabel").pack(anchor=W, pady=(0, 8))

    def path_row(label, var, browse):
        row = ttk.Frame(frm)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=16).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Browse", command=lambda: browse(var)).pack(side="left")

    path_row("Hooks dir", hooks_var, _browse_dir)
    path_row("Data dir", runs_var, _browse_dir)
    path_row("settings.json", settings_var, _browse_file)

    ttk.Separator(frm).pack(fill="x", pady=10)
    ttk.Label(frm, text="Components", style="Heading.TLabel").pack(anchor=W, pady=(0, 8))

    comp_vars = {}
    for c in COMPONENTS:
        if c["kind"] == "tool":
            continue
        v = BooleanVar(value=c.get("default_enabled", True))
        comp_vars[c["id"]] = v
        row = ttk.Frame(frm)
        row.pack(fill="x", pady=1)
        ttk.Checkbutton(row, text=c["label"], variable=v).pack(side="left")
        ttk.Label(row, text="  " + c["description"], style="Muted.TLabel").pack(side="left")

    tools = [c for c in COMPONENTS if c["kind"] == "tool"]
    if tools:
        ttk.Label(frm, text="Included tools (run from the repo)", style="Muted.TLabel").pack(anchor=W, pady=(8, 2))
        for c in tools:
            ttk.Label(frm, text=f"  {c['label']}: {c['path']}", style="Muted.TLabel").pack(anchor=W)

    status = Text(frm, height=9, wrap="word", bg="#2b2d31", fg="#e6e6e6", insertbackground="#e6e6e6", relief="flat")

    def log(msg):
        status.configure(state=NORMAL)
        status.insert(END, msg + "\n")
        status.configure(state=DISABLED)
        status.see(END)

    def do_install():
        selected = [
            c for c in COMPONENTS
            if c["kind"] in ("hook", "support") and comp_vars.get(c["id"]) is not None and comp_vars[c["id"]].get()
        ]
        try:
            core.install(selected, hooks_var.get(), runs_var.get(), settings_var.get(), sys.executable, SRC_HOOKS, managed_scripts())
        except Exception as exc:
            log(f"Install failed: {exc}")
            return
        log("Install complete.")
        log(f"Hooks -> {hooks_var.get()}")
        log(f"Data  -> {runs_var.get()}")
        log("Run your analytics with:")
        py = sys.executable
        log(f'  "{py}" "{REPO_ROOT / "analytics" / "analyze.py"}" --runs-dir "{runs_var.get()}"')
        log(f'  "{py}" "{REPO_ROOT / "analytics" / "dashboard.py"}" --runs-dir "{runs_var.get()}"')

    ttk.Button(frm, text="Install", command=do_install, style="Accent.TButton").pack(pady=12)
    status.pack(fill="both", expand=True)

    root.mainloop()
```

- [ ] **Step 5: Implement `installer/__main__.py`**

```python
import sys


def main():
    try:
        import tkinter
    except Exception:
        sys.stderr.write("Tkinter is not available. On Debian/Ubuntu install it with 'sudo apt install python3-tk', then retry.\n")
        return 1
    del tkinter
    from installer.ui import run
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run import-smoke test**

Run: `python -m unittest tests.test_ui_import -v`
Expected: PASS (or SKIP if the environment has no Tkinter).

- [ ] **Step 7: Manual launch check (developer)**

Run: `python -m installer`
Expected: a dark-themed window opens with three path rows, component checkboxes, an Install button, and a status box. Close it without installing.

- [ ] **Step 8: Commit**

```bash
git add installer/theme.py installer/ui.py installer/__main__.py tests/test_ui_import.py
git commit -m "Add Tkinter installer UI"
```

---

### Task 9: Entry scripts

**Files:**
- Create: `install.sh`
- Create: `install.cmd`

- [ ] **Step 1: Implement `install.sh`**

```sh
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python 3.12+ is required but was not found. Install it from https://www.python.org/downloads/ and retry." >&2
  exit 1
fi
exec "$PY" -m installer
```

- [ ] **Step 2: Make it executable and record the bit in git**

Run:
```bash
chmod +x install.sh
git update-index --chmod=+x install.sh 2>/dev/null || true
```

- [ ] **Step 3: Implement `install.cmd`**

```bat
@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m installer
  goto :eof
)
where python >nul 2>nul
if %errorlevel%==0 (
  python -m installer
  goto :eof
)
echo Python 3.12+ is required but was not found.
echo Install it from https://www.python.org/downloads/ and retry.
exit /b 1
```

- [ ] **Step 4: Verify the entry script runs the package**

Run (current OS): on Windows `install.cmd`, on mac/linux `./install.sh`.
Expected: the installer window opens (same as Task 8 Step 7). Close it.

- [ ] **Step 5: Commit**

```bash
git add install.sh install.cmd
git commit -m "Add one-command entry scripts per OS"
```

---

### Task 10: README rewrite

**Files:**
- Modify: `README.md` (replace whole file; create it if absent)

- [ ] **Step 1: Write the README**

Replace `README.md` with:
```markdown
# Claude Hooks Analytics

Telemetry hooks for Claude Code that record how you work with the agent (tool use,
tokens, agents, skills, files, timing, ship signals, red flags) and analytics tools
that turn that data into a report or a browser dashboard. Everything is Python
standard library; there is nothing to `pip install`.

## Install

Clone the repo, then run the one entry script for your OS:

- Windows: double-click `install.cmd` (or run it in a terminal)
- macOS / Linux: `./install.sh`

That launches a small installer app. In it you:

1. Choose where hooks are installed, where data is stored, and which `settings.json`
   to update (your global `~/.claude` or a project `.claude`).
2. Tick the components you want.
3. Click Install.

The installer copies the selected hooks, writes the hooks into your `settings.json`
without touching any of your other settings, and creates the data directory. Re-run
it any time to change paths or add/remove components.

Requirements: Python 3.12+. On some minimal Linux installs you also need Tkinter
(`sudo apt install python3-tk`).

## What it captures

Per session and per subagent: tool-call counts and mix, token usage and cache
efficiency (read from the transcript), agents dispatched, skills invoked, files read
and written, bash command classification and file-mutation targets, permission
denials, conflict-marker red flags, wall-clock vs. active time, and inferred ship
outcome (commit / push / PR / merge).

## Read your data

From the repo, after installing:

```
python analytics/analyze.py            # terminal report
python analytics/dashboard.py          # opens an HTML dashboard in your browser
```

Both accept `--days N` and `--runs-dir PATH`. If you chose a custom data directory,
pass it with `--runs-dir`; the installer prints the exact commands when it finishes.

## Tag sessions (optional)

Set `CLAUDE_SESSION_TAG` in your shell before launching Claude Code to label
sessions (for example `work` vs `personal`); the value is recorded with each session.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Rewrite README around the one-command install"
```

---

### Task 11: Final verification

- [ ] **Step 1: Run the full test suite**

Run: `python -m unittest discover -s tests -t . -v`
Expected: all tests PASS (UI test may SKIP if no Tkinter).

- [ ] **Step 2: End-to-end install into a throwaway location (developer)**

Run:
```bash
python -c "import sys; sys.path.insert(0,'.'); from installer import core; from installer.manifest import COMPONENTS, managed_scripts; from pathlib import Path; import tempfile,json; d=Path(tempfile.mkdtemp()); core.install([c for c in COMPONENTS if c['kind'] in ('hook','support')], d/'hooks', d/'runs', d/'settings.json', sys.executable, Path('hooks'), managed_scripts()); print(json.dumps(json.loads((d/'settings.json').read_text())['hooks'], indent=2)); print('config:', (d/'hooks'/'installer_config.json').read_text())"
```
Expected: prints a `hooks` block containing `SessionStart`, `UserPromptSubmit`,
`PreToolUse` (two), `PostToolUse` (two), `SubagentStop`, `Stop`, with commands
pointing at the throwaway `hooks` dir; and an `installer_config.json` whose
`runs_dir` is the throwaway `runs` dir.

- [ ] **Step 3: Confirm the working tree is clean and the branch is ready**

Run: `git status`
Expected: clean working tree on `feature/installer-and-restructure`.

---

## Notes for the implementer

- User code style: no comments, no docstrings, anywhere. Keep functions short.
- Never run `git commit` with `--no-verify`.
- The hooks and their `_*.py` modules must stay co-located in `hooks/`; they import
  each other by bare name (`from _common import ...`) and are copied flat to the
  install dir.
- `sys.executable` is the interpreter the installer runs under; it is baked into the
  hook commands so they do not depend on PATH.
```
