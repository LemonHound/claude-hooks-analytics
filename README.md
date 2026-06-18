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
outcome (commit / push / PR / merge). With the optional hooks enabled, it also
captures context compaction events, notifications (permission prompts vs. idle),
code churn (lines added/removed), test pass/fail outcomes, and MCP usage by server.

## Read your data

Open the app (`install.cmd` / `install.sh`) and use the **Analytics** section: the
**Text report** and **Open dashboard** buttons run against your Data dir and show a
clickable link to the output. You can do this any time, not just right after
installing.

Or run them from the repo directly:

```
python analytics/analyze.py            # terminal report
python analytics/dashboard.py          # opens an HTML dashboard in your browser
```

Both accept `--days N` and `--runs-dir PATH`; pass `--runs-dir` if you chose a
custom data directory.

## Tag sessions (optional)

Set `CLAUDE_SESSION_TAG` in your shell before launching Claude Code to label
sessions (for example `work` vs `personal`); the value is recorded with each session.
