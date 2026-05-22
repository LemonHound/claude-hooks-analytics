#!/usr/bin/env python3
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


RUNS_DIR = Path.home() / ".claude" / "runs"
SESSIONS_DIR = RUNS_DIR / "sessions"


def _load_sessions(days: int | None) -> list[dict]:
    if not SESSIONS_DIR.exists():
        return []
    cutoff = None
    if days is not None:
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now - days * 86400
    sessions = []
    for p in SESSIONS_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if cutoff is not None:
            ts = d.get("timestamp_start") or ""
            if ts:
                try:
                    s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
                    epoch = datetime.fromisoformat(s).timestamp()
                    if epoch < cutoff:
                        continue
                except Exception:
                    pass
        sessions.append(d)
    return sessions


def _load_artifacts(session_ids: set) -> list[dict]:
    if not RUNS_DIR.exists():
        return []
    artifacts = []
    for p in RUNS_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("session_id") in session_ids:
            artifacts.append(d)
    return artifacts


def _fmt_int(n: int | None) -> str:
    if n is None:
        return "n/a"
    return f"{n:,}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%"


def _fmt_dur(s: float | None) -> str:
    if s is None:
        return "n/a"
    if s < 60:
        return f"{s:.0f}s"
    return f"{s / 60:.1f}m"


def _date_range(sessions: list[dict]) -> str:
    dates = []
    for s in sessions:
        ts = s.get("timestamp_start") or ""
        if ts:
            try:
                d = ts[:10]
                dates.append(d)
            except Exception:
                pass
    if not dates:
        return "unknown"
    return f"{min(dates)} to {max(dates)}"


def _token_by_model(sessions: list[dict], artifacts: list[dict]) -> dict:
    model_totals: dict[str, dict] = {}

    def _add(model, it, ot, cr, cc):
        if not model:
            model = "unknown"
        slot = model_totals.setdefault(model, {
            "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
        })
        slot["input"] += it or 0
        slot["output"] += ot or 0
        slot["cache_read"] += cr or 0
        slot["cache_creation"] += cc or 0

    for s in sessions:
        m = s.get("model")
        _add(m,
             s.get("total_input_tokens"),
             s.get("total_output_tokens"),
             s.get("total_cache_read_tokens"),
             s.get("total_cache_creation_tokens"))

    for a in artifacts:
        m = a.get("model")
        _add(m,
             a.get("input_tokens"),
             a.get("output_tokens"),
             a.get("cache_read_tokens"),
             a.get("cache_creation_tokens"))

    return model_totals


def _cache_efficiency(sessions: list[dict]) -> tuple[float | None, float | None]:
    ratios = [s["cache_hit_ratio"] for s in sessions if s.get("cache_hit_ratio") is not None]
    shares = [s["cache_creation_share"] for s in sessions if s.get("cache_creation_share") is not None]
    avg_ratio = sum(ratios) / len(ratios) if ratios else None
    avg_share = sum(shares) / len(shares) if shares else None
    return avg_ratio, avg_share


def _agent_stats(artifacts: list[dict]) -> dict:
    by_agent: dict[str, dict] = {}
    for a in artifacts:
        agent = a.get("agent") or "unknown"
        slot = by_agent.setdefault(agent, {
            "count": 0, "tool_calls": 0, "outcomes": defaultdict(int),
            "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
        })
        slot["count"] += 1
        slot["tool_calls"] += a.get("tool_call_count") or 0
        outcome = a.get("outcome") or "unknown"
        slot["outcomes"][outcome] += 1
        slot["input"] += a.get("input_tokens") or 0
        slot["output"] += a.get("output_tokens") or 0
        slot["cache_read"] += a.get("cache_read_tokens") or 0
        slot["cache_creation"] += a.get("cache_creation_tokens") or 0
    return by_agent


def _skill_stats(sessions: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for s in sessions:
        for skill in s.get("skills_invoked") or []:
            counts[skill] = counts.get(skill, 0) + 1
    return counts


def _repeat_reads(sessions: list[dict]) -> list[tuple[str, int, int, int]]:
    entries: list[tuple[str, int, int, int]] = []
    for s in sessions:
        rr = s.get("repeat_reads") or {}
        for key, v in rr.items():
            if not isinstance(v, dict):
                continue
            count = v.get("count", 0)
            if count < 2:
                continue
            parts = key.split("|")
            file_path = parts[0] if parts else key
            first_turn = v.get("first_turn", 0)
            last_turn = v.get("last_turn", 0)
            entries.append((file_path, count, first_turn, last_turn))
    entries.sort(key=lambda x: -x[1])
    return entries[:20]


def _outcome_counts(sessions: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for s in sessions:
        o = s.get("outcome") or "no_ship_signal"
        counts[o] = counts.get(o, 0) + 1
    return counts


def _tool_breakdown(sessions: list[dict]) -> dict:
    totals: dict[str, int] = {}
    for s in sessions:
        for tool, n in (s.get("tool_call_breakdown") or {}).items():
            totals[tool] = totals.get(tool, 0) + (n or 0)
    return totals


def _correction_stats(sessions: list[dict]) -> tuple[int, int]:
    total_prompts = sum(s.get("user_prompt_count") or 0 for s in sessions)
    correction_prompts = sum(s.get("correction_like_prompt_count") or 0 for s in sessions)
    return total_prompts, correction_prompts


def _permission_stats(sessions: list[dict]) -> dict:
    totals: dict[str, int] = {}
    for s in sessions:
        for tool, n in (s.get("permission_denied_tools") or {}).items():
            totals[tool] = totals.get(tool, 0) + (n or 0)
    return totals


def _sessions_by_tag(sessions: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in sessions:
        tag = s.get("account_tag") or "untagged"
        counts[tag] = counts.get(tag, 0) + 1
    return counts


def _hr(width: int = 60) -> str:
    return "-" * width


def report(sessions: list[dict], artifacts: list[dict]) -> None:
    n_sessions = len(sessions)
    n_artifacts = len(artifacts)

    print("CLAUDE SESSIONS ANALYSIS")
    print(_hr())
    print(f"Period:     {_date_range(sessions)}")
    print(f"Sessions:   {n_sessions} parent | {n_artifacts} subagent runs")
    tag_counts = _sessions_by_tag(sessions)
    if len(tag_counts) > 1 or "untagged" not in tag_counts:
        for tag, n in sorted(tag_counts.items()):
            print(f"  {tag}: {n}")
    print()

    print("TOKEN EFFICIENCY (parent sessions)")
    print(_hr())
    avg_hit, avg_share = _cache_efficiency(sessions)
    print(f"Avg cache hit ratio:      {_fmt_pct(avg_hit)}")
    print(f"Avg cache creation share: {_fmt_pct(avg_share)}")
    no_transcript = sum(1 for s in sessions if s.get("token_source") == "post_tool_fallback")
    if no_transcript:
        print(f"Sessions missing transcript (zero tokens): {no_transcript}")
    print()

    print("TOKEN USAGE BY MODEL")
    print(_hr())
    model_totals = _token_by_model(sessions, artifacts)
    for model, t in sorted(model_totals.items()):
        total_ctx = t["input"] + t["cache_read"] + t["cache_creation"]
        denom = total_ctx + t["output"]
        hit = t["cache_read"] / total_ctx if total_ctx else None
        print(f"{model}")
        print(f"  Input (new):      {_fmt_int(t['input'])}")
        print(f"  Output:           {_fmt_int(t['output'])}")
        print(f"  Cache reads:      {_fmt_int(t['cache_read'])}")
        print(f"  Cache creations:  {_fmt_int(t['cache_creation'])}")
        print(f"  Cache hit ratio:  {_fmt_pct(hit)}")
    print()

    print("AGENT USAGE")
    print(_hr())
    by_agent = _agent_stats(artifacts)
    if by_agent:
        total_artifact_tokens = sum(
            (a.get("input_tokens") or 0) + (a.get("output_tokens") or 0) for a in artifacts
        )
        for agent, slot in sorted(by_agent.items(), key=lambda x: -x[1]["count"]):
            avg_tools = slot["tool_calls"] / slot["count"] if slot["count"] else 0
            agent_tokens = slot["input"] + slot["output"]
            pct = agent_tokens / total_artifact_tokens if total_artifact_tokens else None
            outcomes = ", ".join(f"{k}:{v}" for k, v in sorted(slot["outcomes"].items()))
            print(f"{agent:30s}  {slot['count']:4d} runs  {avg_tools:5.1f} tools/run  {_fmt_pct(pct)} tokens  [{outcomes}]")
    else:
        print("No subagent artifacts found.")
    print()

    parent_token_total = sum(
        (s.get("total_input_tokens") or 0) + (s.get("total_output_tokens") or 0)
        for s in sessions
    )
    subagent_token_total = sum(
        (a.get("input_tokens") or 0) + (a.get("output_tokens") or 0)
        for a in artifacts
    )
    combined = parent_token_total + subagent_token_total
    if combined:
        print(f"Parent vs subagent token split:")
        print(f"  Parent:   {_fmt_pct(parent_token_total / combined)} ({_fmt_int(parent_token_total)})")
        print(f"  Subagent: {_fmt_pct(subagent_token_total / combined)} ({_fmt_int(subagent_token_total)})")
    print()

    print("SKILLS")
    print(_hr())
    skill_counts = _skill_stats(sessions)
    if skill_counts:
        top = sorted(skill_counts.items(), key=lambda x: -x[1])[:10]
        print(f"Total skill calls: {sum(skill_counts.values())}  |  Unique: {len(skill_counts)}")
        for name, n in top:
            print(f"  {name:40s} {n:4d}")
    else:
        print("No skill invocations recorded.")
    print()

    print("REPEAT FILE READS")
    print(_hr())
    repeats = _repeat_reads(sessions)
    whole_file_total = sum(s.get("whole_file_reads_over_500_lines") or 0 for s in sessions)
    if repeats:
        for file_path, count, first_turn, last_turn in repeats[:10]:
            name = Path(file_path).name if file_path else "(unknown)"
            print(f"  {name:40s} {count}x  turns {first_turn}-{last_turn}  {file_path}")
    else:
        print("No repeat reads detected.")
    if whole_file_total:
        print(f"Whole-file re-reads (likely uncached): {whole_file_total}")
    print()

    print("TOOL USAGE BREAKDOWN")
    print(_hr())
    breakdown = _tool_breakdown(sessions)
    total_tools = sum(breakdown.values())
    for tool, n in sorted(breakdown.items(), key=lambda x: -x[1])[:15]:
        pct = n / total_tools if total_tools else 0
        print(f"  {tool:30s} {n:6,}  ({pct * 100:.1f}%)")
    print()

    print("SESSION OUTCOMES")
    print(_hr())
    outcomes = _outcome_counts(sessions)
    for outcome, n in sorted(outcomes.items(), key=lambda x: -x[1]):
        print(f"  {outcome:30s} {n}")
    print()

    print("CORRECTION-LIKE PROMPTS")
    print(_hr())
    total_prompts, correction_prompts = _correction_stats(sessions)
    print(f"  Total user prompts: {_fmt_int(total_prompts)}")
    pct = correction_prompts / total_prompts if total_prompts else None
    print(f"  Correction-like:    {_fmt_int(correction_prompts)}  ({_fmt_pct(pct)})")
    print()

    denied = _permission_stats(sessions)
    if denied:
        print("PERMISSION DENIALS (by tool)")
        print(_hr())
        for tool, n in sorted(denied.items(), key=lambda x: -x[1]):
            print(f"  {tool:30s} {n}")
        print()

    error_sessions = sum(1 for s in sessions if (s.get("error_count") or 0) > 0)
    if error_sessions:
        total_errors = sum(s.get("error_count") or 0 for s in sessions)
        print("ERRORS")
        print(_hr())
        print(f"  Sessions with errors: {error_sessions} / {n_sessions}")
        print(f"  Total tool errors:    {total_errors}")
        print()

    print("TIMING")
    print(_hr())
    walls = [s["wall_clock_seconds"] for s in sessions if s.get("wall_clock_seconds") is not None]
    actives = [s["active_seconds"] for s in sessions if s.get("active_seconds") is not None]
    if walls:
        print(f"  Avg wall clock:     {_fmt_dur(sum(walls) / len(walls))}")
        print(f"  Total wall clock:   {_fmt_dur(sum(walls))}")
    if actives:
        print(f"  Avg LLM active:     {_fmt_dur(sum(actives) / len(actives))}")


def main():
    ap = argparse.ArgumentParser(description="Analyze Claude Code session telemetry.")
    ap.add_argument("--days", type=int, default=None, help="Limit to last N days (default: all)")
    ap.add_argument("--session", default=None, help="Analyze a single session ID")
    ap.add_argument("--runs-dir", default=None, help="Override runs directory path")
    args = ap.parse_args()

    global RUNS_DIR, SESSIONS_DIR
    if args.runs_dir:
        RUNS_DIR = Path(args.runs_dir)
        SESSIONS_DIR = RUNS_DIR / "sessions"

    sessions = _load_sessions(args.days)
    if args.session:
        sessions = [s for s in sessions if s.get("session_id") == args.session]

    if not sessions:
        print("No session data found.", file=sys.stderr)
        sys.exit(1)

    session_ids = {s["session_id"] for s in sessions if s.get("session_id")}
    artifacts = _load_artifacts(session_ids)

    report(sessions, artifacts)


if __name__ == "__main__":
    main()
