#!/usr/bin/env python3
import argparse
import json
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import os


RUNS_DIR = Path.home() / ".claude" / "runs"
SESSIONS_DIR = RUNS_DIR / "sessions"


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


def _load_sessions(days, runs_dir):
    sd = runs_dir / "sessions"
    if not sd.exists():
        return []
    cutoff = None
    if days is not None:
        cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    sessions = []
    for p in sd.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if cutoff is not None:
            ts = d.get("timestamp_start") or ""
            if ts:
                try:
                    s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
                    if datetime.fromisoformat(s).timestamp() < cutoff:
                        continue
                except Exception:
                    pass
        sessions.append(d)
    sessions.sort(key=lambda x: x.get("timestamp_start") or "")
    return sessions


def _load_artifacts(session_ids, runs_dir):
    if not runs_dir.exists():
        return []
    artifacts = []
    for p in runs_dir.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("session_id") in session_ids:
            artifacts.append(d)
    return artifacts


def build_payload(sessions, artifacts):
    session_ids = {s.get("session_id") for s in sessions if s.get("session_id")}
    artifacts_by_session = defaultdict(list)
    for a in artifacts:
        sid = a.get("session_id")
        if sid:
            artifacts_by_session[sid].append(a)

    daily: dict[str, dict] = {}
    for s in sessions:
        ts = s.get("timestamp_start") or ""
        day = ts[:10] if ts else "unknown"
        if day not in daily:
            daily[day] = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "sessions": 0}
        daily[day]["sessions"] += 1
        daily[day]["input"] += s.get("total_input_tokens") or 0
        daily[day]["output"] += s.get("total_output_tokens") or 0
        daily[day]["cache_read"] += s.get("total_cache_read_tokens") or 0
        daily[day]["cache_creation"] += s.get("total_cache_creation_tokens") or 0
    for a in artifacts:
        ts = a.get("timestamp_start") or ""
        day = ts[:10] if ts else "unknown"
        if day not in daily:
            daily[day] = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "sessions": 0}
        daily[day]["input"] += a.get("input_tokens") or 0
        daily[day]["output"] += a.get("output_tokens") or 0
        daily[day]["cache_read"] += a.get("cache_read_tokens") or 0
        daily[day]["cache_creation"] += a.get("cache_creation_tokens") or 0

    model_totals: dict[str, dict] = {}

    def _add_model(model, it, ot, cr, cc):
        m = model or "unknown"
        slot = model_totals.setdefault(m, {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0})
        slot["input"] += it or 0
        slot["output"] += ot or 0
        slot["cache_read"] += cr or 0
        slot["cache_creation"] += cc or 0

    for s in sessions:
        _add_model(s.get("model"), s.get("total_input_tokens"), s.get("total_output_tokens"),
                   s.get("total_cache_read_tokens"), s.get("total_cache_creation_tokens"))
    for a in artifacts:
        _add_model(a.get("model"), a.get("input_tokens"), a.get("output_tokens"),
                   a.get("cache_read_tokens"), a.get("cache_creation_tokens"))

    agent_stats: dict[str, dict] = {}
    for a in artifacts:
        agent = a.get("agent") or "unknown"
        slot = agent_stats.setdefault(agent, {
            "count": 0, "tool_calls": 0, "input": 0, "output": 0,
            "outcomes": defaultdict(int), "errors": 0, "files_written": 0,
        })
        slot["count"] += 1
        slot["tool_calls"] += a.get("tool_call_count") or 0
        slot["input"] += a.get("input_tokens") or 0
        slot["output"] += a.get("output_tokens") or 0
        slot["outcomes"][a.get("outcome") or "unknown"] += 1
        slot["errors"] += a.get("error_count") or 0
        slot["files_written"] += len(a.get("files_written") or [])
    for ag in agent_stats.values():
        ag["outcomes"] = dict(ag["outcomes"])

    skill_counts: dict[str, int] = {}
    for s in sessions:
        for sk in s.get("skills_invoked") or []:
            skill_counts[sk] = skill_counts.get(sk, 0) + 1

    outcome_counts: dict[str, int] = {}
    for s in sessions:
        o = s.get("outcome") or "no_ship_signal"
        outcome_counts[o] = outcome_counts.get(o, 0) + 1

    tool_totals: dict[str, int] = {}
    for s in sessions:
        for tool, n in (s.get("tool_call_breakdown") or {}).items():
            tool_totals[tool] = tool_totals.get(tool, 0) + (n or 0)

    repeat_reads = []
    for s in sessions:
        rr = s.get("repeat_reads") or {}
        for key, v in rr.items():
            if not isinstance(v, dict):
                continue
            count = v.get("count", 0)
            if count < 2:
                continue
            parts = key.split("|")
            repeat_reads.append({
                "file": parts[0] if parts else key,
                "count": count,
                "first_turn": v.get("first_turn", 0),
                "last_turn": v.get("last_turn", 0),
                "session_id": s.get("session_id"),
            })
    repeat_reads.sort(key=lambda x: -x["count"])

    cache_trend = []
    for s in sessions:
        ts = s.get("timestamp_start") or ""
        if s.get("cache_hit_ratio") is not None:
            cache_trend.append({
                "date": ts[:10] if ts else "unknown",
                "hit_ratio": s["cache_hit_ratio"],
                "session_id": s.get("session_id"),
            })

    session_list = []
    for s in sessions:
        sid = s.get("session_id") or ""
        sa = artifacts_by_session.get(sid, [])
        session_list.append({
            "session_id": sid,
            "timestamp_start": s.get("timestamp_start") or "",
            "timestamp_end": s.get("timestamp_end") or "",
            "wall_clock_seconds": s.get("wall_clock_seconds"),
            "active_seconds": s.get("active_seconds"),
            "model": s.get("model"),
            "account_tag": s.get("account_tag"),
            "outcome": s.get("outcome") or "no_ship_signal",
            "total_input_tokens": s.get("total_input_tokens") or 0,
            "total_output_tokens": s.get("total_output_tokens") or 0,
            "total_cache_read_tokens": s.get("total_cache_read_tokens") or 0,
            "total_cache_creation_tokens": s.get("total_cache_creation_tokens") or 0,
            "cache_hit_ratio": s.get("cache_hit_ratio"),
            "tool_call_count": s.get("tool_call_count") or 0,
            "user_prompt_count": s.get("user_prompt_count") or 0,
            "correction_like_prompt_count": s.get("correction_like_prompt_count") or 0,
            "error_count": s.get("error_count") or 0,
            "skills_invoked": s.get("skills_invoked") or [],
            "tool_call_breakdown": s.get("tool_call_breakdown") or {},
            "subagent_count": len(sa),
            "subagents": [
                {
                    "agent": a.get("agent"),
                    "outcome": a.get("outcome"),
                    "tool_call_count": a.get("tool_call_count") or 0,
                    "input_tokens": a.get("input_tokens") or 0,
                    "output_tokens": a.get("output_tokens") or 0,
                    "files_written": len(a.get("files_written") or []),
                    "wall_clock_seconds": a.get("wall_clock_seconds"),
                }
                for a in sa
            ],
        })

    total_prompts = sum(s.get("user_prompt_count") or 0 for s in sessions)
    correction_prompts = sum(s.get("correction_like_prompt_count") or 0 for s in sessions)

    dated = [s["timestamp_start"][:10] for s in sessions if s.get("timestamp_start")]
    days_range = {"start": min(dated), "end": max(dated)} if dated else None

    churn = {
        "added": sum(s.get("lines_added") or 0 for s in sessions),
        "removed": sum(s.get("lines_removed") or 0 for s in sessions),
    }
    churn["net"] = churn["added"] - churn["removed"]
    tests = {
        "runs": sum(s.get("test_run_count") or 0 for s in sessions),
        "passed": sum(s.get("test_pass_total") or 0 for s in sessions),
        "failed": sum(s.get("test_fail_total") or 0 for s in sessions),
        "failed_runs": sum(s.get("test_failed_runs") or 0 for s in sessions),
    }
    mcp_totals: dict[str, int] = {}
    for s in sessions:
        for srv, n in (s.get("mcp_server_breakdown") or {}).items():
            mcp_totals[srv] = mcp_totals.get(srv, 0) + (n or 0)
    compaction_total = sum(s.get("compaction_count") or 0 for s in sessions)
    notification_total = sum(s.get("notification_count") or 0 for s in sessions)
    permission_request_total = sum(s.get("permission_request_count") or 0 for s in sessions)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_count": len(sessions),
        "artifact_count": len(artifacts),
        "days_range": days_range,
        "daily_tokens": dict(sorted(daily.items())),
        "model_totals": model_totals,
        "agent_stats": agent_stats,
        "skill_counts": skill_counts,
        "outcome_counts": outcome_counts,
        "tool_totals": tool_totals,
        "repeat_reads": repeat_reads[:30],
        "cache_trend": cache_trend,
        "sessions": session_list,
        "total_prompts": total_prompts,
        "correction_prompts": correction_prompts,
        "churn": churn,
        "tests": tests,
        "mcp_totals": mcp_totals,
        "compaction_total": compaction_total,
        "notification_total": notification_total,
        "permission_request_total": permission_request_total,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Sessions Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #222536;
    --border: #2e3148;
    --accent: #7c6af5;
    --accent2: #4fc3f7;
    --accent3: #69f0ae;
    --accent4: #ff6b6b;
    --text: #e2e4f0;
    --text2: #8b8fa8;
    --text3: #5a5e78;
  }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; font-size: 14px; line-height: 1.5; }
  h1 { font-size: 20px; font-weight: 600; }
  h2 { font-size: 15px; font-weight: 600; color: var(--text2); text-transform: uppercase; letter-spacing: .06em; }
  h3 { font-size: 14px; font-weight: 600; }
  a { color: var(--accent); text-decoration: none; cursor: pointer; }
  a:hover { text-decoration: underline; }

  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 14px 24px; display: flex; align-items: center; gap: 16px; position: sticky; top: 0; z-index: 10; }
  header .meta { font-size: 12px; color: var(--text2); margin-left: auto; }

  nav { display: flex; gap: 4px; }
  nav button { background: none; border: 1px solid transparent; color: var(--text2); padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  nav button:hover { background: var(--surface2); color: var(--text); }
  nav button.active { background: var(--surface2); border-color: var(--border); color: var(--text); }

  main { padding: 24px; max-width: 1400px; margin: 0 auto; }

  .page { display: none; }
  .page.active { display: block; }

  .grid { display: grid; gap: 16px; }
  .grid-2 { grid-template-columns: repeat(2, 1fr); }
  .grid-3 { grid-template-columns: repeat(3, 1fr); }
  .grid-4 { grid-template-columns: repeat(4, 1fr); }

  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 18px; }
  .card-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 14px; }
  .card-sub { font-size: 11px; color: var(--text3); font-weight: 400; text-transform: none; letter-spacing: 0; }

  .stat { display: flex; flex-direction: column; gap: 4px; }
  .stat .label { font-size: 12px; color: var(--text2); }
  .stat .value { font-size: 26px; font-weight: 700; }
  .stat .sub { font-size: 12px; color: var(--text3); }

  .badge { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .badge-green { background: rgba(105,240,174,.15); color: var(--accent3); }
  .badge-blue { background: rgba(79,195,247,.15); color: var(--accent2); }
  .badge-red { background: rgba(255,107,107,.15); color: var(--accent4); }
  .badge-purple { background: rgba(124,106,245,.15); color: var(--accent); }
  .badge-gray { background: rgba(139,143,168,.12); color: var(--text2); }

  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; padding: 7px 10px; color: var(--text2); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  td { padding: 7px 10px; border-bottom: 1px solid rgba(46,49,72,.5); vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(124,106,245,.05); }
  .num { text-align: right; font-variant-numeric: tabular-nums; }

  canvas { display: block; }

  .chart-empty { color: var(--text3); font-size: 12px; padding: 40px 0; text-align: center; }

  .detail-panel { position: fixed; top: 0; right: -540px; width: 540px; height: 100vh; background: var(--surface); border-left: 1px solid var(--border); overflow-y: auto; transition: right .3s; z-index: 100; padding: 24px; }
  .detail-panel.open { right: 0; }
  .detail-panel .close-btn { float: right; background: none; border: none; color: var(--text2); font-size: 20px; cursor: pointer; line-height: 1; }
  .detail-panel .close-btn:hover { color: var(--text); }

  .section-gap { margin-top: 24px; }

  .pill-row { display: flex; flex-wrap: wrap; gap: 6px; }
  .pill { padding: 3px 9px; border-radius: 20px; font-size: 12px; background: var(--surface2); border: 1px solid var(--border); color: var(--text2); }

  .subagent-row { background: var(--surface2); border-radius: 6px; padding: 10px 12px; margin-bottom: 6px; }

  .empty { color: var(--text3); font-style: italic; padding: 12px 0; }

  .filter-row { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; }
  input[type=text], select { background: var(--surface2); border: 1px solid var(--border); color: var(--text); padding: 6px 10px; border-radius: 6px; font-size: 13px; outline: none; }
  input[type=text]:focus, select:focus { border-color: var(--accent); }
  input[type=text] { width: 280px; }

  .note { font-size: 11px; color: var(--text3); margin-top: 8px; }

  @media (max-width: 900px) {
    .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<header>
  <h1>Claude Sessions</h1>
  <nav>
    <button class="active" onclick="showPage('overview')">Overview</button>
    <button onclick="showPage('tokens')">Tokens</button>
    <button onclick="showPage('agents')">Agents</button>
    <button onclick="showPage('sessions')">Sessions</button>
    <button onclick="showPage('efficiency')">Efficiency</button>
    <button onclick="showPage('activity')">Activity</button>
  </nav>
  <div class="meta" id="meta"></div>
</header>

<main>
  <!-- OVERVIEW -->
  <div id="page-overview" class="page active">
    <div class="grid grid-4" style="margin-bottom:16px" id="kpi-row"></div>
    <div class="grid grid-2">
      <div class="card">
        <div class="card-header"><h2>Tokens per Day</h2><span id="daily-range" class="card-sub"></span></div>
        <div id="chart-daily-wrap"><canvas id="chart-daily"></canvas></div>
      </div>
      <div class="card">
        <div class="card-header">
          <h2>Session Outcomes</h2>
        </div>
        <div id="chart-outcomes-wrap"><canvas id="chart-outcomes"></canvas></div>
        <div class="note">no_ship_signal = default when no git push/PR/commit was detected in the session</div>
      </div>
    </div>
    <div class="grid grid-2 section-gap">
      <div class="card">
        <div class="card-header"><h2>Top Tools</h2></div>
        <div id="tool-bars"></div>
      </div>
      <div class="card">
        <div class="card-header"><h2>Skills Invoked</h2></div>
        <div id="skill-bars"></div>
      </div>
    </div>
  </div>

  <!-- TOKENS -->
  <div id="page-tokens" class="page">
    <div class="grid grid-2" style="margin-bottom:16px">
      <div class="card">
        <div class="card-header"><h2>By Model</h2><span class="card-sub">unknown = model not captured at session start</span></div>
        <table id="model-table">
          <thead><tr><th>Model</th><th class="num">Input (new)</th><th class="num">Output</th><th class="num">Cache Read</th><th class="num">Cache Miss</th><th class="num" title="Cache reads / (input + cache read + cache miss)">Cache Hit %</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <div class="card">
        <div class="card-header"><h2>Cache Hit Rate Trend</h2><span class="card-sub">per session</span></div>
        <div id="chart-cache-wrap"><canvas id="chart-cache"></canvas></div>
      </div>
    </div>
    <div class="card">
      <div class="card-header"><h2>Daily Token Breakdown</h2><span id="daily-range2" class="card-sub"></span></div>
      <div id="chart-daily2-wrap"><canvas id="chart-daily2"></canvas></div>
    </div>
  </div>

  <!-- AGENTS -->
  <div id="page-agents" class="page">
    <div class="card" style="margin-bottom:16px">
      <div class="card-header">
        <h2>Agent Usage</h2>
        <span class="card-sub">unknown = agent type not resolved from sidecar; outcomes unknown = pre-dates outcome tracking</span>
      </div>
      <table id="agent-table">
        <thead><tr><th>Agent</th><th class="num">Runs</th><th>Outcomes</th><th class="num" title="Tool calls per run">Avg Tools</th><th class="num" title="Total files written/edited across all runs">Files Written</th><th class="num">Errors</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <div class="grid grid-2">
      <div class="card">
        <div class="card-header"><h2>Agent Token Share</h2><span class="card-sub">combined in+out</span></div>
        <div id="chart-agent-tokens-wrap"><canvas id="chart-agent-tokens"></canvas></div>
      </div>
      <div class="card">
        <div class="card-header"><h2>Run Frequency</h2></div>
        <div id="agent-bars"></div>
      </div>
    </div>
  </div>

  <!-- SESSIONS -->
  <div id="page-sessions" class="page">
    <div class="filter-row">
      <input type="text" id="session-search" placeholder="Search session ID, model, tag..." oninput="renderSessionTable()">
      <select id="session-outcome-filter" onchange="renderSessionTable()">
        <option value="">All outcomes</option>
      </select>
    </div>
    <div class="card">
      <table id="session-table">
        <thead><tr><th>Date</th><th>Model</th><th>Tag</th><th>Outcome</th><th class="num">In Tokens</th><th class="num">Out Tokens</th><th class="num" title="Cache reads / total context tokens">Cache Hit %</th><th class="num">Tools</th><th class="num">Agents</th><th class="num">Duration</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <!-- EFFICIENCY -->
  <div id="page-efficiency" class="page">
    <div class="grid grid-3" style="margin-bottom:16px" id="efficiency-kpis"></div>
    <div class="grid grid-2">
      <div class="card">
        <div class="card-header"><h2>Repeat File Reads</h2><span class="card-sub">same file read 2+ times in a session</span></div>
        <table id="repeat-table">
          <thead><tr><th>File</th><th class="num">Reads</th><th class="num">Turn range</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <div class="card">
        <div class="card-header"><h2>Correction-Like Prompts</h2></div>
        <div id="correction-detail"></div>
      </div>
    </div>
  </div>

  <!-- ACTIVITY -->
  <div id="page-activity" class="page">
    <div class="grid grid-4" style="margin-bottom:16px" id="activity-kpis"></div>
    <div class="grid grid-2">
      <div class="card">
        <div class="card-header"><h2>MCP Usage</h2><span class="card-sub">tool calls by server</span></div>
        <div id="mcp-bars"></div>
      </div>
    </div>
  </div>
</main>

<!-- DETAIL PANEL -->
<div id="detail-panel" class="detail-panel">
  <button class="close-btn" onclick="closePanel()">&#x2715;</button>
  <div id="detail-content"></div>
</div>

<script>
const DATA = __DATA_PLACEHOLDER__;

function fmt(n) {
  if (n == null) return 'n/a';
  if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
  if (n >= 1e3) return (n/1e3).toFixed(1)+'k';
  return String(n);
}
function fmtFull(n) {
  if (n == null) return 'n/a';
  return n.toLocaleString();
}
function fmtPct(v) {
  if (v == null) return 'n/a';
  return (v*100).toFixed(1)+'%';
}
function fmtDur(s) {
  if (s == null) return 'n/a';
  if (s < 60) return s.toFixed(0)+'s';
  return (s/60).toFixed(1)+'m';
}
function fmtDate(ts) {
  if (!ts) return '';
  return ts.slice(0,10)+' '+ts.slice(11,16);
}

const COLORS = ['#7c6af5','#4fc3f7','#69f0ae','#ff6b6b','#ffb347','#e879f9','#38bdf8','#a3e635','#fb923c','#f472b6'];

// Lazy rendering: charts are rendered the first time a page becomes visible.
// Canvas clientWidth is 0 on hidden pages, breaking chart layout.
const pageRendered = {};

function renderPageCharts(name) {
  if (name === 'overview') {
    renderDailyChart('chart-daily', 'daily-range');
    renderOutcomesChart();
  } else if (name === 'tokens') {
    renderCacheTrend();
    renderDailyChart('chart-daily2', 'daily-range2');
  } else if (name === 'agents') {
    renderAgentTokenPie();
  }
}

function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  document.querySelectorAll('nav button').forEach(b => {
    if (b.getAttribute('onclick') && b.getAttribute('onclick').includes("'"+name+"'")) {
      b.classList.add('active');
    }
  });
  if (!pageRendered[name]) {
    pageRendered[name] = true;
    renderPageCharts(name);
  }
}

function closePanel() {
  document.getElementById('detail-panel').classList.remove('open');
}

function outcomeClass(o) {
  if (!o || o === 'no_ship_signal') return 'badge-gray';
  if (o === 'completed' || o.startsWith('shipped') || o.startsWith('pr_') || o.startsWith('pushed') || o.startsWith('committed')) return 'badge-green';
  if (o === 'completed_with_errors') return 'badge-red';
  if (o === 'no_tools_called') return 'badge-blue';
  return 'badge-purple';
}

function renderKPIs() {
  const sessions = DATA.sessions;
  const totalIn = sessions.reduce((a,s)=>a+s.total_input_tokens,0);
  const totalOut = sessions.reduce((a,s)=>a+s.total_output_tokens,0);
  const totalCR = sessions.reduce((a,s)=>a+s.total_cache_read_tokens,0);
  const ratios = sessions.filter(s=>s.cache_hit_ratio!=null).map(s=>s.cache_hit_ratio);
  const avgHit = ratios.length ? ratios.reduce((a,v)=>a+v,0)/ratios.length : null;
  const el = document.getElementById('kpi-row');
  const range = DATA.days_range ? `${DATA.days_range.start} to ${DATA.days_range.end}` : 'all time';
  el.innerHTML = `
    <div class="card stat"><span class="label">Sessions</span><span class="value">${DATA.session_count}</span><span class="sub">${DATA.artifact_count} subagent runs &bull; ${range}</span></div>
    <div class="card stat"><span class="label">Total Tokens</span><span class="value">${fmt(totalIn+totalOut)}</span><span class="sub">${fmt(totalIn)} in / ${fmt(totalOut)} out</span></div>
    <div class="card stat"><span class="label">Cache Reads</span><span class="value">${fmt(totalCR)}</span><span class="sub">avg hit rate ${fmtPct(avgHit)}</span></div>
    <div class="card stat"><span class="label">Corrections</span><span class="value">${DATA.correction_prompts}</span><span class="sub">${fmtPct(DATA.total_prompts ? DATA.correction_prompts/DATA.total_prompts : null)} of ${DATA.total_prompts} prompts</span></div>
  `;
}

function renderDailyChart(canvasId, rangeId) {
  try {
    const canvas = document.getElementById(canvasId);
    const W = canvas.parentElement.clientWidth;
    if (W < 50) return;
    const daily = DATA.daily_tokens;
    const days = Object.keys(daily).filter(d => d !== 'unknown').sort();
    if (!days.length) {
      canvas.parentElement.innerHTML = '<div class="chart-empty">No dated session data</div>';
      return;
    }
    if (rangeId) {
      const el = document.getElementById(rangeId);
      if (el) el.textContent = days[0] + (days.length > 1 ? ' to ' + days[days.length-1] : '');
    }
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const H = 180;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W+'px'; canvas.style.height = H+'px';
    ctx.scale(dpr, dpr);
    ctx.clearRect(0,0,W,H);

    const pad = {l:52,r:16,t:20,b:28};
    const maxTotal = Math.max(...days.map(d => (daily[d].input||0)+(daily[d].output||0)+(daily[d].cache_read||0)), 1);
    const bw = Math.max(2, (W-pad.l-pad.r)/days.length - 3);

    ctx.font = '11px system-ui';
    for (let i=0;i<=4;i++) {
      const y = pad.t + (H-pad.t-pad.b)*i/4;
      const val = maxTotal*(1-i/4);
      ctx.fillStyle = '#5a5e78';
      ctx.fillText(fmt(val), 2, y+4);
      ctx.strokeStyle = 'rgba(46,49,72,.4)';
      ctx.beginPath(); ctx.moveTo(pad.l,y); ctx.lineTo(W-pad.r,y); ctx.stroke();
    }

    days.forEach((day, i) => {
      const slotW = (W-pad.l-pad.r)/days.length;
      const x = pad.l + i*slotW + slotW/2 - bw/2;
      const d = daily[day];
      const total = (d.input||0)+(d.output||0)+(d.cache_read||0);
      if (!total) return;
      const stackH = (H-pad.t-pad.b)*total/maxTotal;
      let yy = H-pad.b;
      [[d.cache_read||0,'#4fc3f7'],[d.input||0,'#7c6af5'],[d.output||0,'#69f0ae']].forEach(([val, color]) => {
        const sh = stackH*(val/total);
        ctx.fillStyle = color;
        ctx.fillRect(x, yy-sh, bw, sh);
        yy -= sh;
      });
      const step = Math.max(1, Math.ceil(days.length/12));
      if (i % step === 0 || i === days.length-1) {
        ctx.fillStyle = '#5a5e78';
        ctx.fillText(day.slice(5), x+bw/2-12, H-4);
      }
    });

    ctx.font = '11px system-ui';
    [['#7c6af5','Input (new)'],['#69f0ae','Output'],['#4fc3f7','Cache read']].forEach(([c,label],i) => {
      ctx.fillStyle = c; ctx.fillRect(pad.l+i*95,2,9,9);
      ctx.fillStyle='#8b8fa8'; ctx.fillText(label, pad.l+i*95+12, 11);
    });
  } catch(e) {
    console.error('renderDailyChart:', e);
  }
}

function renderOutcomesChart() {
  try {
    const canvas = document.getElementById('chart-outcomes');
    const W = canvas.parentElement.clientWidth;
    if (W < 50) return;
    const oc = DATA.outcome_counts;
    const labels = Object.keys(oc);
    if (!labels.length) return;
    const H = 180;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W*dpr; canvas.height = H*dpr;
    canvas.style.width=W+'px'; canvas.style.height=H+'px';
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr,dpr);
    const legendLines = labels.length;
    const legendH = legendLines * 16 + 4;
    const cy = (H-legendH)/2, cx = W/2;
    const r = Math.min(cx-8, cy-8, 70);
    const total = labels.reduce((a,k)=>a+oc[k],0);
    let start = -Math.PI/2;
    labels.forEach((label,i) => {
      const slice = oc[label]/total * Math.PI*2;
      ctx.beginPath(); ctx.moveTo(cx,cy);
      ctx.arc(cx,cy,r,start,start+slice);
      ctx.fillStyle = COLORS[i%COLORS.length];
      ctx.fill();
      start += slice;
    });
    ctx.font='11px system-ui';
    const ly0 = H - legendH + 4;
    labels.forEach((label,i) => {
      ctx.fillStyle=COLORS[i%COLORS.length]; ctx.fillRect(8, ly0+i*16, 9, 9);
      ctx.fillStyle='#8b8fa8'; ctx.fillText(`${label}: ${oc[label]}`, 21, ly0+i*16+9);
    });
  } catch(e) {
    console.error('renderOutcomesChart:', e);
  }
}

function renderBars(containerId, data, color) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const entries = Object.entries(data).sort((a,b)=>b[1]-a[1]).slice(0,12);
  if (!entries.length) { el.innerHTML='<div class="empty">None recorded</div>'; return; }
  const max = entries[0][1];
  el.innerHTML = entries.map(([name,n]) => `
    <div style="margin-bottom:9px">
      <div style="display:flex;justify-content:space-between;margin-bottom:3px">
        <span style="font-size:12px;color:var(--text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:70%">${name}</span>
        <span style="font-size:12px;color:var(--text3)">${fmtFull(n)}</span>
      </div>
      <div style="background:var(--surface2);border-radius:4px;height:5px">
        <div style="background:${color||'var(--accent)'};border-radius:4px;height:5px;width:${(n/max*100).toFixed(1)}%"></div>
      </div>
    </div>
  `).join('');
}

function renderActivity() {
  const c = DATA.churn || {added:0, removed:0, net:0};
  const t = DATA.tests || {runs:0, passed:0, failed:0, failed_runs:0};
  const el = document.getElementById('activity-kpis');
  if (el) {
    el.innerHTML = `
      <div class="card stat"><span class="label">Code Churn</span><span class="value">${fmt(c.net)}</span><span class="sub">${fmt(c.added)} added / ${fmt(c.removed)} removed</span></div>
      <div class="card stat"><span class="label">Test Runs</span><span class="value">${t.runs}</span><span class="sub">${t.failed_runs} failed runs &bull; ${fmt(t.passed)}/${fmt(t.failed)} pass/fail</span></div>
      <div class="card stat"><span class="label">Compactions</span><span class="value">${DATA.compaction_total||0}</span><span class="sub">context compaction events</span></div>
      <div class="card stat"><span class="label">Permission Prompts</span><span class="value">${DATA.permission_request_total||0}</span><span class="sub">of ${DATA.notification_total||0} notifications</span></div>
    `;
  }
  renderBars('mcp-bars', DATA.mcp_totals || {}, 'var(--accent2)');
}

function renderModelTable() {
  const mt = DATA.model_totals;
  const tbody = document.querySelector('#model-table tbody');
  tbody.innerHTML = Object.entries(mt).sort((a,b) => {
    const ta=(a[1].input||0)+(a[1].output||0), tb=(b[1].input||0)+(b[1].output||0);
    return tb-ta;
  }).map(([model,t]) => {
    const ctx = (t.input||0)+(t.cache_read||0)+(t.cache_creation||0);
    const hit = ctx ? t.cache_read/ctx : null;
    return `<tr>
      <td>${model}</td>
      <td class="num">${fmtFull(t.input)}</td>
      <td class="num">${fmtFull(t.output)}</td>
      <td class="num">${fmtFull(t.cache_read)}</td>
      <td class="num">${fmtFull(t.cache_creation)}</td>
      <td class="num">${fmtPct(hit)}</td>
    </tr>`;
  }).join('');
}

function renderCacheTrend() {
  try {
    const canvas = document.getElementById('chart-cache');
    const W = canvas.parentElement.clientWidth;
    if (W < 50) return;
    const trend = DATA.cache_trend;
    if (!trend.length) {
      canvas.parentElement.innerHTML = '<div class="chart-empty">No cache hit data recorded</div>';
      return;
    }
    const H = 200;
    const dpr = window.devicePixelRatio||1;
    canvas.width=W*dpr; canvas.height=H*dpr;
    canvas.style.width=W+'px'; canvas.style.height=H+'px';
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr,dpr);
    const pad={l:42,r:16,t:16,b:28};
    const n = trend.length;

    for (let i=0;i<=4;i++) {
      const y = pad.t+(H-pad.t-pad.b)*i/4;
      ctx.strokeStyle='rgba(46,49,72,.4)'; ctx.beginPath(); ctx.moveTo(pad.l,y); ctx.lineTo(W-pad.r,y); ctx.stroke();
      ctx.fillStyle='#5a5e78'; ctx.font='11px system-ui'; ctx.fillText(fmtPct(1-i/4),2,y+4);
    }

    const pts = trend.map((t,i) => ({
      x: pad.l + (n > 1 ? i*(W-pad.l-pad.r)/(n-1) : (W-pad.l-pad.r)/2),
      y: pad.t + (H-pad.t-pad.b)*(1-t.hit_ratio),
    }));

    ctx.strokeStyle='#7c6af5'; ctx.lineWidth=2; ctx.beginPath();
    pts.forEach((p,i) => i===0 ? ctx.moveTo(p.x,p.y) : ctx.lineTo(p.x,p.y));
    ctx.stroke();
    pts.forEach(p => {
      ctx.fillStyle='#7c6af5'; ctx.beginPath(); ctx.arc(p.x,p.y,3,0,Math.PI*2); ctx.fill();
    });

    const step = Math.max(1, Math.ceil(n/10));
    trend.forEach((t,i) => {
      if (i % step === 0 || i === n-1) {
        ctx.fillStyle='#5a5e78'; ctx.font='11px system-ui';
        ctx.fillText(t.date.slice(5), pts[i].x-12, H-4);
      }
    });
  } catch(e) {
    console.error('renderCacheTrend:', e);
  }
}

function renderAgentTable() {
  const tbody = document.querySelector('#agent-table tbody');
  const as = DATA.agent_stats;
  tbody.innerHTML = Object.entries(as).sort((a,b)=>b[1].count-a[1].count).map(([agent,s])=>{
    const avgT = s.count ? (s.tool_calls/s.count).toFixed(1) : '0';
    const oc = Object.entries(s.outcomes).sort((a,b)=>b[1]-a[1])
      .map(([k,v])=>`<span class="badge ${outcomeClass(k)}" style="margin-right:2px">${k}:${v}</span>`).join('');
    const fw = s.files_written || 0;
    return `<tr>
      <td>${agent}</td>
      <td class="num">${s.count}</td>
      <td>${oc||'<span style="color:var(--text3)">none</span>'}</td>
      <td class="num">${avgT}</td>
      <td class="num">${fw}</td>
      <td class="num" style="color:${(s.errors||0)>0?'var(--accent4)':'var(--text3)'}">${s.errors||0}</td>
    </tr>`;
  }).join('');
}

function renderAgentTokenPie() {
  try {
    const canvas = document.getElementById('chart-agent-tokens');
    const W = canvas.parentElement.clientWidth;
    if (W < 50) return;
    const as = DATA.agent_stats;
    const entries = Object.entries(as)
      .map(([k,v]) => [k,(v.input||0)+(v.output||0)])
      .sort((a,b)=>b[1]-a[1]);
    const total = entries.reduce((a,e)=>a+e[1],0);
    if (!total) {
      canvas.parentElement.innerHTML = '<div class="chart-empty">No token data in subagent artifacts<br><span style="font-size:11px">Token capture requires agent_transcript_path in SubagentStop payload</span></div>';
      return;
    }
    const H = 220;
    const dpr = window.devicePixelRatio||1;
    canvas.width=W*dpr; canvas.height=H*dpr;
    canvas.style.width=W+'px'; canvas.style.height=H+'px';
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr,dpr);
    const legendLines = Math.min(entries.length, 6);
    const legendH = legendLines * 16 + 8;
    const cy = (H-legendH)/2, cx=W/2;
    const r = Math.min(cx-8, cy-8, 80);
    let start=-Math.PI/2;
    entries.forEach(([name,val],i) => {
      const slice=val/total*Math.PI*2;
      ctx.beginPath(); ctx.moveTo(cx,cy);
      ctx.arc(cx,cy,r,start,start+slice);
      ctx.fillStyle=COLORS[i%COLORS.length]; ctx.fill();
      start+=slice;
    });
    ctx.font='11px system-ui';
    const ly0 = H - legendH + 4;
    entries.slice(0,6).forEach(([name,val],i) => {
      ctx.fillStyle=COLORS[i%COLORS.length]; ctx.fillRect(8, ly0+i*16, 9, 9);
      ctx.fillStyle='#8b8fa8';
      const label = name.length>22 ? name.slice(0,20)+'...' : name;
      ctx.fillText(`${label} (${fmtPct(val/total)})`, 21, ly0+i*16+9);
    });
  } catch(e) {
    console.error('renderAgentTokenPie:', e);
  }
}

let allSessions = [];
function populateSessionFilters() {
  allSessions = DATA.sessions;
  const sel = document.getElementById('session-outcome-filter');
  const ocs = [...new Set(allSessions.map(s=>s.outcome))].sort();
  sel.innerHTML = '<option value="">All outcomes</option>' + ocs.map(o=>`<option value="${o}">${o}</option>`).join('');
}

function renderSessionTable() {
  const search = (document.getElementById('session-search').value || '').toLowerCase();
  const outcomeF = document.getElementById('session-outcome-filter').value;
  const rows = allSessions.filter(s => {
    if (outcomeF && s.outcome !== outcomeF) return false;
    if (search) {
      const hay = [(s.outcome||''),(s.model||''),(s.account_tag||''),(s.session_id||'')].join(' ').toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });
  const tbody = document.querySelector('#session-table tbody');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty" style="text-align:center;padding:24px">No sessions match</td></tr>';
    return;
  }
  tbody.innerHTML = rows.slice().reverse().map(s => `
    <tr onclick="openSession('${s.session_id}')" style="cursor:pointer">
      <td style="white-space:nowrap">${fmtDate(s.timestamp_start)}</td>
      <td style="font-size:11px;color:var(--text2);max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.model||'unknown'}</td>
      <td>${s.account_tag?`<span class="badge badge-blue">${s.account_tag}</span>`:''}</td>
      <td><span class="badge ${outcomeClass(s.outcome)}">${s.outcome}</span></td>
      <td class="num">${fmt(s.total_input_tokens)}</td>
      <td class="num">${fmt(s.total_output_tokens)}</td>
      <td class="num">${fmtPct(s.cache_hit_ratio)}</td>
      <td class="num">${s.tool_call_count}</td>
      <td class="num">${s.subagent_count}</td>
      <td class="num">${fmtDur(s.wall_clock_seconds)}</td>
    </tr>
  `).join('');
}

function openSession(sessionId) {
  const s = DATA.sessions.find(x=>x.session_id===sessionId);
  if (!s) return;
  const toolEntries = Object.entries(s.tool_call_breakdown).sort((a,b)=>b[1]-a[1]);
  document.getElementById('detail-content').innerHTML = `
    <h3 style="margin-bottom:6px">${fmtDate(s.timestamp_start)}</h3>
    <div style="font-size:11px;color:var(--text3);margin-bottom:16px;word-break:break-all">${s.session_id}</div>

    <div class="grid grid-2" style="gap:10px;margin-bottom:16px">
      <div class="card"><span class="label" style="font-size:12px;color:var(--text2)">Model</span><div style="font-size:13px;margin-top:4px">${s.model||'unknown'}</div></div>
      <div class="card"><span class="label" style="font-size:12px;color:var(--text2)">Outcome</span><div style="margin-top:4px"><span class="badge ${outcomeClass(s.outcome)}">${s.outcome}</span></div></div>
      <div class="card"><span class="label" style="font-size:12px;color:var(--text2)">Duration</span><div style="font-size:18px;font-weight:600;margin-top:2px">${fmtDur(s.wall_clock_seconds)}</div></div>
      <div class="card"><span class="label" style="font-size:12px;color:var(--text2)">Cache Hit</span><div style="font-size:18px;font-weight:600;margin-top:2px">${fmtPct(s.cache_hit_ratio)}</div></div>
    </div>

    <div class="card" style="margin-bottom:12px">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px">
        <div><span style="color:var(--text2)">Input:</span> ${fmtFull(s.total_input_tokens)}</div>
        <div><span style="color:var(--text2)">Output:</span> ${fmtFull(s.total_output_tokens)}</div>
        <div><span style="color:var(--text2)">Cache reads:</span> ${fmtFull(s.total_cache_read_tokens)}</div>
        <div><span style="color:var(--text2)">Cache miss:</span> ${fmtFull(s.total_cache_creation_tokens)}</div>
        <div><span style="color:var(--text2)">Tools:</span> ${s.tool_call_count}</div>
        <div><span style="color:var(--text2)">Prompts:</span> ${s.user_prompt_count}</div>
        <div><span style="color:var(--text2)">Corrections:</span> ${s.correction_like_prompt_count}</div>
        <div><span style="color:var(--text2)">Errors:</span> ${s.error_count}</div>
      </div>
    </div>

    ${s.skills_invoked.length ? `
    <h3 style="margin-bottom:8px">Skills Invoked</h3>
    <div class="pill-row" style="margin-bottom:12px">${s.skills_invoked.map(sk=>`<span class="pill">${sk}</span>`).join('')}</div>
    ` : ''}

    ${toolEntries.length ? `
    <h3 style="margin-bottom:8px">Tool Breakdown</h3>
    <div style="margin-bottom:12px;columns:2;column-gap:16px">
      ${toolEntries.map(([t,n])=>`<div style="font-size:12px;padding:2px 0;break-inside:avoid"><span style="color:var(--text2)">${t}</span> <span style="float:right">${n}</span></div>`).join('')}
    </div>
    ` : ''}

    ${s.subagents.length ? `
    <h3 style="margin-bottom:8px">Subagents (${s.subagents.length})</h3>
    ${s.subagents.map(a=>`
      <div class="subagent-row">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-weight:600;font-size:13px">${a.agent||'unknown'}</span>
          <span class="badge ${outcomeClass(a.outcome)}">${a.outcome||'?'}</span>
        </div>
        <div style="font-size:12px;color:var(--text2);margin-top:4px">
          ${a.input_tokens||a.output_tokens ? `${fmtFull(a.input_tokens)} in / ${fmtFull(a.output_tokens)} out &bull; ` : ''}${a.tool_call_count} tools${a.files_written ? ` &bull; ${a.files_written} files written` : ''} &bull; ${fmtDur(a.wall_clock_seconds)}
        </div>
      </div>
    `).join('')}
    ` : ''}
  `;
  document.getElementById('detail-panel').classList.add('open');
}

function renderRepeatReads() {
  const tbody = document.querySelector('#repeat-table tbody');
  const rr = DATA.repeat_reads;
  if (!rr.length) {
    tbody.innerHTML='<tr><td colspan="3" class="empty">None detected</td></tr>';
    return;
  }
  tbody.innerHTML = rr.slice(0,20).map(r=>`
    <tr>
      <td style="font-size:12px;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${r.file}">${r.file.split(/[/\\]/).pop()||r.file}</td>
      <td class="num" style="color:${r.count>3?'var(--accent4)':r.count>1?'var(--accent)':'var(--text)'}">${r.count}x</td>
      <td class="num" style="color:var(--text3)">t${r.first_turn}&ndash;t${r.last_turn}</td>
    </tr>
  `).join('');
}

function renderEfficiencyKPIs() {
  const sessions = DATA.sessions;
  const ratios = sessions.filter(s=>s.cache_hit_ratio!=null).map(s=>s.cache_hit_ratio);
  const avgHit = ratios.length ? ratios.reduce((a,v)=>a+v,0)/ratios.length : null;
  const pct = DATA.total_prompts ? DATA.correction_prompts/DATA.total_prompts : null;
  document.getElementById('efficiency-kpis').innerHTML = `
    <div class="card stat"><span class="label">Avg Cache Hit Rate</span><span class="value">${fmtPct(avgHit)}</span><span class="sub">cache reads / total context tokens</span></div>
    <div class="card stat"><span class="label">Correction Rate</span><span class="value">${fmtPct(pct)}</span><span class="sub">${DATA.correction_prompts} of ${DATA.total_prompts} prompts</span></div>
    <div class="card stat"><span class="label">Repeat-Read Files</span><span class="value">${DATA.repeat_reads.length}</span><span class="sub">files read 2+ times in a session</span></div>
  `;
}

function renderCorrectionDetail() {
  const el = document.getElementById('correction-detail');
  const t = DATA.total_prompts, c = DATA.correction_prompts;
  const pct = t ? c/t : 0;
  el.innerHTML = `
    <div style="margin-bottom:16px">
      <div style="font-size:32px;font-weight:700;margin-bottom:4px">${fmtPct(pct)}</div>
      <div style="color:var(--text2);font-size:13px">${c} correction-like out of ${t} total user prompts</div>
    </div>
    <div style="background:var(--surface2);border-radius:6px;height:10px;margin-bottom:12px">
      <div style="background:${pct>0.2?'var(--accent4)':pct>0.1?'#ffb347':'var(--accent3)'};border-radius:6px;height:10px;width:${Math.min(pct*100,100).toFixed(1)}%"></div>
    </div>
    <div style="font-size:12px;color:var(--text3)">Matched on: "no,", "don't", "stop", "that's wrong", "revert", "undo", "retry", "scrap", etc.</div>
  `;
}

document.addEventListener('DOMContentLoaded', () => {
  const d = new Date(DATA.generated_at);
  document.getElementById('meta').textContent = `${d.toLocaleString()} · ${DATA.session_count} sessions`;

  renderKPIs();
  renderBars('tool-bars', DATA.tool_totals, 'var(--accent)');
  renderBars('skill-bars', DATA.skill_counts, 'var(--accent2)');
  renderModelTable();
  renderAgentTable();
  renderBars('agent-bars', Object.fromEntries(Object.entries(DATA.agent_stats).map(([k,v])=>[k,v.count])), 'var(--accent3)');
  populateSessionFilters();
  renderSessionTable();
  renderEfficiencyKPIs();
  renderRepeatReads();
  renderCorrectionDetail();
  renderActivity();

  pageRendered['overview'] = true;
  renderPageCharts('overview');

  window.addEventListener('resize', () => {
    const active = document.querySelector('.page.active');
    if (!active) return;
    const name = active.id.replace('page-','');
    delete pageRendered[name];
    pageRendered[name] = true;
    renderPageCharts(name);
  });

  document.getElementById('detail-panel').addEventListener('click', e => {
    if (e.target === document.getElementById('detail-panel')) closePanel();
  });
});
</script>
</body>
</html>
"""


def generate_html(payload: dict) -> str:
    data_json = json.dumps(payload, default=str)
    return HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json)


def main():
    ap = argparse.ArgumentParser(description="Launch Claude sessions dashboard in browser.")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--session", default=None)
    ap.add_argument("--runs-dir", default=None)
    ap.add_argument("--output", default=None, help="Write HTML to file instead of opening browser")
    args = ap.parse_args()

    runs_dir = _resolve_runs_dir(args.runs_dir)

    sessions = _load_sessions(args.days, runs_dir)
    if args.session:
        sessions = [s for s in sessions if s.get("session_id") == args.session]

    if not sessions:
        print("No session data found.", file=sys.stderr)
        sys.exit(1)

    session_ids = {s["session_id"] for s in sessions if s.get("session_id")}
    artifacts = _load_artifacts(session_ids, runs_dir)

    payload = build_payload(sessions, artifacts)
    html = generate_html(payload)

    if args.output:
        Path(args.output).write_text(html, encoding="utf-8")
        print(f"Written to {args.output}")
        return

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8", prefix="claude_dash_"
    ) as f:
        f.write(html)
        path = f.name

    print(f"Opening dashboard: {path}")
    webbrowser.open(f"file:///{path.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
