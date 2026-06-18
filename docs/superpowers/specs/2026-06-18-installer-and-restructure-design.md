# Installer + repo restructure design

Date: 2026-06-18
Status: approved

## Goal

Make this repo clone-and-go on Windows, macOS, and Linux. A user clones, runs one
entry script for their OS, and a guided GUI walks them through choosing paths,
selecting which components to install, and running the install (copy files + a
non-destructive `settings.json` upsert). Everything beyond the single entry script
is the GUI.

## Constraints

- Hooks run on every tool call and must remain stdlib-only. No third-party deps.
- The installer GUI is also stdlib-only: Tkinter, not PySide6. A venv cannot be
  shipped (absolute paths + OS/arch-specific binaries), so zero-install is the goal.
- The `settings.json` merge must never remove or overwrite existing user settings;
  it only adds missing hook command entries.
- The installer installs and oversees EVERYTHING the project offers, present and
  future. It is not limited to telemetry hooks. New components appear automatically
  by declaring themselves in a manifest.
- Paths are fully user-customizable: hooks directory and data directory.

## Folder structure

```
claude-hooks-analytics/
  install.sh            # mac/linux entry: locate python3, launch installer
  install.cmd           # windows entry: locate python, launch installer
  README.md
  pyproject.toml
  hooks/                # everything copied to the install hooks dir
    session_start.py user_prompt.py pre_tool.py post_tool.py
    post_edit_check.py subagent_stop.py session_end.py
    record_subagent_feedback.py
    _common.py _config.py _segments.py _text.py _transcript.py
  analytics/            # run-in-place reporting
    analyze.py  dashboard.py
  installer/            # the installer app
    __main__.py         # entry: launches the wizard
    manifest.py         # declarative registry of installable components
    core.py             # copy + settings merge + config write (no UI)
    ui.py               # Tkinter wizard
    theme.py            # dark palette
  docs/
```

Hooks and their `_`-prefixed shared modules stay in one folder: they are copied
flat to the install directory and import each other directly
(`from _common import ...`). The `_` prefix distinguishes shared modules from hook
entrypoints. Analytics and installer are separated by purpose.

## Installer architecture

Three isolated units.

### manifest.py

A list of component descriptors, the single source of truth for what can be
installed. Each descriptor:

- `id`: stable identifier
- `label`: short display name
- `description`: one line shown next to the toggle
- `kind`: `hook` or `tool`
- `default_enabled`: bool
- for `hook` components: `event`, `matcher` (optional), `async` (bool),
  `timeout` (optional), `script` (filename in `hooks/`)

Adding a future component is: drop the file in `hooks/` (or `analytics/`) and add
one manifest entry.

### core.py

Pure functions, no Tkinter, fully unit-testable:

- resolve paths (hooks dir, data dir, settings path)
- copy selected hook scripts plus always-copy the shared `_*.py` modules
- write `<hooks_dir>/installer_config.json` = `{"runs_dir": "<chosen>"}`
- non-destructively upsert `settings.json`: never touch non-hook settings or hook
  entries owned by other tools. For each selected component, remove any prior entry
  for that same script (matched by script filename, regardless of hooks dir, to
  avoid stale duplicates when relocating/reinstalling) and add the new entry
  pointing at the chosen hooks dir. Deselected components are removed.
- create data directories (`runs/`, `runs/events`, `runs/sessions`, `runs/prompts`)

### ui.py + theme.py

A Tkinter wizard driving `core.py`:

1. choose hooks dir, data dir, and settings scope (global `~/.claude` vs a project
   `.claude`)
2. per-component checkboxes populated from the manifest
3. review screen (what will be copied, which settings keys will be added)
4. Install button
5. result screen

`theme.py` applies a simple dark palette (RoAR has no theme to copy).

## Custom-path mechanism

`_common.py` resolves the data directory by precedence:

1. `CLAUDE_HOOKS_RUNS_DIR` environment variable
2. `installer_config.json` located relative to its own `__file__` (i.e. next to the
   installed hooks)
3. default `~/.claude/runs`

Analyzers (`analyze.py`, `dashboard.py`) resolve by precedence:

1. `--runs-dir` argument
2. `CLAUDE_HOOKS_RUNS_DIR` environment variable
3. `installer_config.json` at the default hooks location (`~/.claude/hooks/`)
4. default `~/.claude/runs`

The installer's result screen prints ready-to-run analytics commands with the
chosen `--runs-dir` so a custom data dir works with copy-paste and no env setup. No
shell-profile or registry edits; hooks read a file next to themselves, so it works
on any OS.

## Entry scripts

`install.sh` and `install.cmd` are thin: locate a Python 3.12+, then run
`python -m installer`. No venv (everything is stdlib). If Python is missing, or
Tkinter is missing (some Linux distros need `python3-tk`), print a one-line fix and
exit non-zero. A future component that declares dependencies is when the installer
creates a venv; not now.

## README

Rewritten so the entire getting-started is: clone, then run `install.sh`
(mac/linux) or `install.cmd` (Windows); everything else is the GUI. Keep a short
"what it captures / how to read your data" section pointing at the analytics tools.

## Testing

- Unit tests for `core.py`: settings merge is non-destructive, only selected hooks
  added, config file written correctly, custom paths honored, commands point at the
  chosen hooks dir.
- Unit tests for `_common.py` path-resolution precedence.
- The Tkinter UI is thin glue over `core.py` and stays untested.

## Out of scope

- Part-1 data-gap fixes (PreCompact, code churn, test pass/fail, MCP classification).
- The 3 personal workflow hooks (`check_stale_branch.py`, `worktree_cleanup.py`,
  `worktree_track.py`).

The manifest makes adding any of these later a one-line change.
