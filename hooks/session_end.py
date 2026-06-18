import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    ARTIFACTS_DIR,
    SCHEMA_VERSION,
    append_event,
    now_iso,
    read_events,
    read_stdin_json,
    update_agent_map,
    write_session_rollup,
)
from _transcript import iter_assistant_messages, read_transcript_usage


SIDECAR_TTL_SECONDS = 86400


def _parse_message_epoch(ts):
    if not isinstance(ts, str) or not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, OSError):
        return None


def _walk_assistant_messages(transcript_path):
    peak = None
    final = None
    for msg in iter_assistant_messages(transcript_path):
        usage = msg.get("usage") or {}
        it = usage.get("input_tokens")
        if not isinstance(it, int):
            it = 0
        if peak is None or it > peak:
            peak = it
        final = it
    return peak, final


def build_turn_summaries(events: list[dict], transcript_path: str | None) -> list[dict]:
    prompts = [e for e in events if e.get("phase") == "user_prompt_submit"]
    if not prompts:
        return []

    epochs = [e.get("_epoch") for e in events if isinstance(e.get("_epoch"), (int, float))]
    last_epoch = max(epochs) if epochs else None

    pre_events_with_epoch = [e for e in events if e.get("phase") == "pre_tool" and isinstance(e.get("_epoch"), (int, float))]

    transcript_messages: list[dict] = []
    for msg in iter_assistant_messages(transcript_path):
        epoch = msg.get("epoch")
        if epoch is None:
            ts = msg.get("ts")
            epoch = _parse_message_epoch(ts) if ts else None
        usage = msg.get("usage") or {}
        transcript_messages.append({
            "epoch": epoch,
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_read": int(usage.get("cache_read_input_tokens") or 0),
            "cache_creation": int(usage.get("cache_creation_input_tokens") or 0),
        })

    summaries: list[dict] = []
    for idx, prompt in enumerate(prompts):
        start = prompt.get("_epoch")
        if idx + 1 < len(prompts):
            end = prompts[idx + 1].get("_epoch")
            inclusive_end = False
        else:
            end = last_epoch if last_epoch is not None else start
            inclusive_end = True

        if not isinstance(start, (int, float)):
            start = 0.0
        if not isinstance(end, (int, float)):
            end = start

        tool_calls = 0
        agents_dispatched = 0
        for pe in pre_events_with_epoch:
            ep = pe.get("_epoch")
            if ep < start:
                continue
            if inclusive_end:
                if ep > end:
                    continue
            else:
                if ep >= end:
                    continue
            tool_calls += 1
            if pe.get("tool_name") in ("Agent", "Task"):
                agents_dispatched += 1

        tokens_in = 0
        tokens_out = 0
        cache_read = 0
        cache_creation = 0
        peak = None
        final = None
        for tm in transcript_messages:
            ep = tm["epoch"]
            if ep is None:
                continue
            if ep < start:
                continue
            if inclusive_end:
                if ep > end:
                    continue
            else:
                if ep >= end:
                    continue
            tokens_in += tm["input_tokens"]
            tokens_out += tm["output_tokens"]
            cache_read += tm["cache_read"]
            cache_creation += tm["cache_creation"]
            if peak is None or tm["input_tokens"] > peak:
                peak = tm["input_tokens"]
            final = tm["input_tokens"]

        wall = round(end - start, 3) if isinstance(start, (int, float)) and isinstance(end, (int, float)) else 0.0
        if wall < 0:
            wall = 0.0

        summaries.append({
            "phase": "turn_summary",
            "schema_version": SCHEMA_VERSION,
            "turn_index": idx,
            "prompt_hash": prompt.get("prompt_hash"),
            "started_epoch": start if isinstance(start, (int, float)) else None,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cache_read": cache_read,
            "cache_creation": cache_creation,
            "tool_calls": tool_calls,
            "agents_dispatched": agents_dispatched,
            "peak_input_tokens": peak,
            "final_input_tokens": final,
            "wall_clock_seconds": wall,
        })

    return summaries


def derive_permission_denied_red_flags(events: list[dict]) -> list[dict]:
    post_tool_ids: set = set()
    for e in events:
        if e.get("phase") == "post_tool":
            tid = e.get("tool_use_id")
            if tid is not None:
                post_tool_ids.add(tid)

    prompt_records: list[tuple[float, str | None]] = []
    for e in events:
        if e.get("phase") != "user_prompt_submit":
            continue
        ep = e.get("_epoch")
        if not isinstance(ep, (int, float)):
            continue
        prompt_records.append((ep, e.get("prompt_hash")))
    prompt_records.sort(key=lambda r: r[0])

    def _resolve_turn(epoch):
        if not isinstance(epoch, (int, float)) or not prompt_records:
            return None, None
        idx = -1
        for i, (ep, _) in enumerate(prompt_records):
            if ep <= epoch:
                idx = i
            else:
                break
        if idx < 0:
            return None, None
        return idx, prompt_records[idx][1]

    red_flags: list[dict] = []
    for e in events:
        if e.get("phase") != "pre_tool":
            continue
        tid = e.get("tool_use_id")
        if tid is None or tid in post_tool_ids:
            continue
        turn_index, prompt_hash = _resolve_turn(e.get("_epoch"))
        red_flags.append({
            "phase": "red_flag",
            "kind": "permission_denied",
            "inferred_from": "missing_post_tool",
            "tool_name": e.get("tool_name"),
            "tool_use_id": tid,
            "tool_input_summary": e.get("tool_input_summary") or {},
            "prompt_hash": prompt_hash,
            "turn_index": turn_index,
            "schema_version": SCHEMA_VERSION,
        })
    return red_flags


def compute_subagent_totals(artifacts: list[dict]) -> tuple[dict, dict]:
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "artifact_count": 0,
    }
    attribution: dict = {}
    for art in artifacts:
        agent = art.get("agent") or "unknown"
        it = art.get("input_tokens") or 0
        ot = art.get("output_tokens") or 0
        cr = art.get("cache_read_tokens") or 0
        cc = art.get("cache_creation_tokens") or 0
        wall = art.get("wall_clock_seconds") or 0
        files_written = len(art.get("files_written") or [])
        outcome = art.get("outcome") or ""

        totals["input_tokens"] += it
        totals["output_tokens"] += ot
        totals["cache_read_tokens"] += cr
        totals["cache_creation_tokens"] += cc
        totals["artifact_count"] += 1

        slot = attribution.setdefault(agent, {
            "invocations": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "wall_clock_seconds": 0.0,
            "files_written": 0,
            "outcomes": {},
            "agent_attribution_source_breakdown": {},
        })
        slot["invocations"] += 1
        slot["input_tokens"] += it
        slot["output_tokens"] += ot
        slot["cache_read_tokens"] += cr
        slot["cache_creation_tokens"] += cc
        slot["wall_clock_seconds"] += wall or 0
        slot["files_written"] += files_written
        if outcome:
            slot["outcomes"][outcome] = slot["outcomes"].get(outcome, 0) + 1
        source = art.get("agent_attribution_source") or "unknown"
        breakdown = slot["agent_attribution_source_breakdown"]
        breakdown[source] = breakdown.get(source, 0) + 1

    for agent, slot in attribution.items():
        files = slot["files_written"]
        slot["tokens_per_file_written"] = (
            round((slot["input_tokens"] + slot["output_tokens"]) / files, 1) if files else None
        )
        slot["wall_clock_seconds"] = round(slot["wall_clock_seconds"], 3)
        agent_denominator = (
            slot["cache_read_tokens"] + slot["cache_creation_tokens"] + slot["input_tokens"]
        )
        if agent_denominator:
            slot["cache_hit_ratio"] = round(slot["cache_read_tokens"] / agent_denominator, 4)
            slot["cache_creation_share"] = round(slot["cache_creation_tokens"] / agent_denominator, 4)
        else:
            slot["cache_hit_ratio"] = None
            slot["cache_creation_share"] = None

    return totals, attribution


def build_rollup(
    events: list[dict],
    transcript_path: str | None,
    payload: dict,
    now_fn: Callable[[], str] = now_iso,
    artifacts: list[dict] | None = None,
) -> dict:
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"

    post = [e for e in events if e.get("phase") == "post_tool"]
    pre = [e for e in events if e.get("phase") == "pre_tool"]

    agents_invoked = sorted({
        e.get("agent_type")
        for e in pre
        if e.get("tool_name") in ("Agent", "Task") and e.get("agent_type")
    })
    skills_invoked = sorted({
        (e.get("tool_input_summary") or {}).get("skill")
        for e in pre
        if e.get("tool_name") == "Skill"
    } - {None})

    post_input = sum((e.get("input_tokens") or 0) for e in post)
    post_output = sum((e.get("output_tokens") or 0) for e in post)
    post_cache_read = sum((e.get("cache_read_tokens") or 0) for e in post)
    post_cache_creation = sum((e.get("cache_creation_tokens") or 0) for e in post)
    error_count = sum(1 for e in post if e.get("is_error"))
    post_model = _dominant_model(post)

    transcript_usage = read_transcript_usage(transcript_path) if transcript_path else None
    if transcript_usage is not None:
        input_tokens = transcript_usage["input_tokens"]
        output_tokens = transcript_usage["output_tokens"]
        cache_read = transcript_usage["cache_read_input_tokens"]
        cache_creation = transcript_usage["cache_creation_input_tokens"]
        token_source = "transcript"
    else:
        input_tokens = post_input
        output_tokens = post_output
        cache_read = post_cache_read
        cache_creation = post_cache_creation
        token_source = "post_tool_fallback"

    model = post_model
    if not model and transcript_usage is not None:
        model = transcript_usage.get("dominant_model")

    peak_input_tokens, final_input_tokens = _walk_assistant_messages(transcript_path)

    ship_signals = _infer_ship_outcome(pre)
    existing_red_flags = [e for e in events if e.get("phase") == "red_flag"]
    derived_permission_flags = derive_permission_denied_red_flags(events)
    existing_permission_ids = {
        rf.get("tool_use_id")
        for rf in existing_red_flags
        if rf.get("kind") == "permission_denied" and rf.get("tool_use_id") is not None
    }
    new_permission_flags = [
        rf for rf in derived_permission_flags
        if rf.get("tool_use_id") not in existing_permission_ids
    ]
    red_flags = existing_red_flags + new_permission_flags
    permission_denied_flags = [rf for rf in red_flags if rf.get("kind") == "permission_denied"]
    permission_denied_tools: dict[str, int] = {}
    for rf in permission_denied_flags:
        name = rf.get("tool_name") or "unknown"
        permission_denied_tools[name] = permission_denied_tools.get(name, 0) + 1
    permission_denied_count = len(permission_denied_flags)
    user_prompts = [e for e in events if e.get("phase") == "user_prompt_submit"]
    correction_count = sum(1 for e in user_prompts if e.get("is_correction_like"))

    bash_category_breakdown = _bash_category_breakdown(pre)
    powershell_category_breakdown = _powershell_category_breakdown(pre)
    bash_file_targets = _bash_file_targets(pre)

    turns = build_turn_summaries(events, transcript_path)
    repeat_reads, whole_file_reads_over_500_lines = _aggregate_reads(pre, turns)
    toolsearch_aggregate = _aggregate_toolsearch(pre, post)

    first_epoch = events[0].get("_epoch") if events else None
    last_epoch = events[-1].get("_epoch") if events else None
    wall_clock_seconds = round(last_epoch - first_epoch, 3) if first_epoch and last_epoch else None

    active_seconds, tool_exec_seconds = _compute_active_time(events)
    idle_seconds = None
    if wall_clock_seconds is not None and active_seconds is not None:
        idle_seconds = round(max(wall_clock_seconds - active_seconds - (tool_exec_seconds or 0), 0.0), 3)

    if artifacts is None:
        artifacts = []
    subagent_totals, agent_attribution = compute_subagent_totals(artifacts)

    cache_denominator = cache_read + cache_creation + input_tokens
    if cache_denominator:
        cache_hit_ratio = round(cache_read / cache_denominator, 4)
        cache_creation_share = round(cache_creation / cache_denominator, 4)
    else:
        cache_hit_ratio = None
        cache_creation_share = None

    skills_aggregate = _build_skills_aggregate(pre, turns)
    tool_call_count = len(pre)
    pending_red_flags: list[dict] = []
    pending_red_flags.extend(new_permission_flags)

    account_tag = next(
        (e.get("account_tag") for e in events
         if e.get("phase") == "session_start" and e.get("account_tag")),
        None,
    )

    compaction_count, compaction_triggers = _compaction_summary(events)
    notification_count, notification_kinds, permission_request_count = _notification_summary(events)
    lines_added, lines_removed = _churn_summary(pre)
    mcp_call_count, mcp_server_breakdown = _mcp_summary(pre)
    test_run_count, test_pass_total, test_fail_total, test_failed_runs = _test_summary(post)

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "model": model,
        "account_tag": account_tag,
        "timestamp_start": events[0].get("_ts") if events else now_fn(),
        "timestamp_end": now_fn(),
        "wall_clock_seconds": wall_clock_seconds,
        "active_seconds": active_seconds,
        "tool_execution_seconds": tool_exec_seconds,
        "idle_seconds": idle_seconds,
        "total_input_tokens": input_tokens,
        "total_output_tokens": output_tokens,
        "total_cache_read_tokens": cache_read,
        "total_cache_creation_tokens": cache_creation,
        "cache_hit_ratio": cache_hit_ratio,
        "cache_creation_share": cache_creation_share,
        "token_source": token_source,
        "peak_input_tokens": peak_input_tokens,
        "final_input_tokens": final_input_tokens,
        "total_input_tokens_with_subagents": input_tokens + subagent_totals["input_tokens"],
        "total_output_tokens_with_subagents": output_tokens + subagent_totals["output_tokens"],
        "total_cache_read_tokens_with_subagents": cache_read + subagent_totals["cache_read_tokens"],
        "total_cache_creation_tokens_with_subagents": cache_creation + subagent_totals["cache_creation_tokens"],
        "subagent_totals": subagent_totals,
        "agent_attribution": agent_attribution,
        "agents_invoked": agents_invoked,
        "agent_count": len(agents_invoked),
        "skills_invoked": skills_invoked,
        "skills_aggregate": skills_aggregate,
        "tool_call_count": tool_call_count,
        "tool_call_breakdown": _breakdown(pre),
        "bash_category_breakdown": bash_category_breakdown,
        "powershell_category_breakdown": powershell_category_breakdown,
        "bash_file_targets": bash_file_targets,
        "error_count": error_count,
        "red_flag_count": len(red_flags),
        "red_flag_kinds": sorted({e.get("kind") for e in red_flags} - {None}),
        "permission_denied_count": permission_denied_count,
        "permission_denied_tools": permission_denied_tools,
        "user_prompt_count": len(user_prompts),
        "correction_like_prompt_count": correction_count,
        "turn_count": len(turns),
        "turns": turns,
        "repeat_reads": repeat_reads,
        "whole_file_reads_over_500_lines": whole_file_reads_over_500_lines,
        "toolsearch_aggregate": toolsearch_aggregate,
        "compaction_count": compaction_count,
        "compaction_triggers": compaction_triggers,
        "notification_count": notification_count,
        "notification_kinds": notification_kinds,
        "permission_request_count": permission_request_count,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "net_lines": lines_added - lines_removed,
        "mcp_call_count": mcp_call_count,
        "mcp_server_breakdown": mcp_server_breakdown,
        "test_run_count": test_run_count,
        "test_pass_total": test_pass_total,
        "test_fail_total": test_fail_total,
        "test_failed_runs": test_failed_runs,
        "stop_reason": payload.get("stop_reason") or "session_end",
        "ship_signals": ship_signals,
        "outcome": ship_signals.get("inferred_outcome", ""),
        "_pending_red_flags": pending_red_flags,
    }


def _load_subagent_artifacts(session_id: str) -> list[dict]:
    artifacts = []
    for path in ARTIFACTS_DIR.glob("*.json"):
        try:
            art = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if art.get("session_id") != session_id:
            continue
        artifacts.append(art)
    return artifacts


def _prune_sidecar(session_id: str, now_epoch: float | None = None) -> None:
    cutoff_now = now_epoch if isinstance(now_epoch, (int, float)) else time.time()
    cutoff = cutoff_now - SIDECAR_TTL_SECONDS

    def _fn(m: dict):
        stale = [
            k for k, v in list(m.items())
            if isinstance(v, dict)
            and isinstance(v.get("started_epoch"), (int, float))
            and v.get("started_epoch") < cutoff
        ]
        for k in stale:
            m.pop(k, None)
        return m

    try:
        update_agent_map(session_id, _fn)
    except Exception:
        pass


def main():
    payload = read_stdin_json()
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"

    append_event(session_id, {"phase": "session_end", "raw_payload": payload})
    events = read_events(session_id)
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath")
    artifacts = _load_subagent_artifacts(session_id)

    _prune_sidecar(session_id)

    rollup = build_rollup(events, transcript_path, payload, artifacts=artifacts)
    for turn in rollup.get("turns") or []:
        append_event(session_id, dict(turn))
    for flag in rollup.pop("_pending_red_flags", None) or []:
        append_event(session_id, dict(flag))
    write_session_rollup(session_id, rollup)


def _compute_active_time(events):
    ordered = [e for e in events if e.get("_epoch") is not None]
    ordered.sort(key=lambda e: e.get("_epoch"))

    tool_pairs = []
    pending = {}
    for e in ordered:
        phase = e.get("phase")
        tid = e.get("tool_use_id")
        if phase == "pre_tool" and tid:
            pending[tid] = e.get("_epoch")
        elif phase == "post_tool" and tid and tid in pending:
            tool_pairs.append((pending.pop(tid), e.get("_epoch")))

    tool_exec = round(sum(end - start for start, end in tool_pairs if end and start), 3)

    user_prompts = [e for e in ordered if e.get("phase") == "user_prompt_submit"]
    if not user_prompts:
        return None, tool_exec if tool_pairs else None

    session_end_epoch = next(
        (e.get("_epoch") for e in reversed(ordered) if e.get("phase") == "session_end"),
        ordered[-1].get("_epoch"),
    )

    boundaries = [up.get("_epoch") for up in user_prompts] + [session_end_epoch]

    active = 0.0
    for i in range(len(user_prompts)):
        turn_start = boundaries[i]
        turn_end = boundaries[i + 1]
        if not turn_start or not turn_end or turn_end <= turn_start:
            continue
        turn_tool_ends = [
            end for (start, end) in tool_pairs
            if start is not None and end is not None and start >= turn_start and end <= turn_end
        ]
        if not turn_tool_ends:
            continue
        last_tool_end = max(turn_tool_ends)
        turn_tool_exec = sum(
            end - start for (start, end) in tool_pairs
            if start is not None and end is not None and start >= turn_start and end <= turn_end
        )
        llm_seconds = (last_tool_end - turn_start) - turn_tool_exec
        if llm_seconds > 0:
            active += llm_seconds

    return round(active, 3), tool_exec


def _bash_category_breakdown(pre_events):
    counts = {}
    for e in pre_events:
        if e.get("tool_name") != "Bash":
            continue
        for cat in e.get("bash_categories") or []:
            counts[cat] = counts.get(cat, 0) + 1
    return counts


def _powershell_category_breakdown(pre_events):
    counts = {}
    for e in pre_events:
        if e.get("tool_name") != "PowerShell":
            continue
        for cat in e.get("powershell_categories") or []:
            counts[cat] = counts.get(cat, 0) + 1
    return counts


def _bash_file_targets(pre_events):
    targets = set()
    for e in pre_events:
        if e.get("tool_name") != "Bash":
            continue
        for t in e.get("bash_file_targets") or []:
            targets.add(t)
    return sorted(targets)[:200]


def _infer_ship_outcome(pre_events):
    signals = {
        "committed": False,
        "pushed": False,
        "pr_created": False,
        "pr_merged": False,
        "auto_merge_enabled": False,
        "inferred_outcome": "",
    }
    for e in pre_events:
        if e.get("tool_name") not in ("Bash", "PowerShell"):
            continue
        cmd = ((e.get("tool_input_summary") or {}).get("command") or "").lower()
        if not cmd:
            continue
        if "git commit" in cmd and "--amend" not in cmd:
            signals["committed"] = True
        if cmd.startswith("git push") or " git push" in cmd:
            signals["pushed"] = True
        if "gh pr create" in cmd:
            signals["pr_created"] = True
        if "gh pr merge" in cmd:
            if "--auto" in cmd:
                signals["auto_merge_enabled"] = True
            else:
                signals["pr_merged"] = True
    if signals["pr_merged"] or signals["auto_merge_enabled"]:
        signals["inferred_outcome"] = "shipped"
    elif signals["pr_created"]:
        signals["inferred_outcome"] = "pr_open"
    elif signals["pushed"]:
        signals["inferred_outcome"] = "pushed_no_pr"
    elif signals["committed"]:
        signals["inferred_outcome"] = "committed_local"
    else:
        signals["inferred_outcome"] = "no_ship_signal"
    return signals


def _dominant_model(post_events):
    counts = {}
    for e in post_events:
        m = e.get("model")
        if m:
            counts[m] = counts.get(m, 0) + 1
    return max(counts, key=counts.get) if counts else None


def _breakdown(events):
    counts = {}
    for e in events:
        name = e.get("tool_name") or "unknown"
        counts[name] = counts.get(name, 0) + 1
    return counts


def _turn_index_for_epoch(turns: list[dict], events: list[dict], epoch) -> int:
    if not isinstance(epoch, (int, float)):
        return 0
    if turns:
        prompt_epochs = []
        for e in events:
            if e.get("phase") == "user_prompt_submit" and isinstance(e.get("_epoch"), (int, float)):
                prompt_epochs.append(e.get("_epoch"))
        idx = 0
        for i, ep in enumerate(prompt_epochs):
            if ep <= epoch:
                idx = i
            else:
                break
        return idx
    return 0


def _aggregate_reads(pre_events: list[dict], turns: list[dict]) -> tuple[dict, int]:
    reads = [e for e in pre_events if e.get("tool_name") == "Read"]
    aggregate: dict = {}
    path_counts: dict = {}
    whole_file_paths: list[str] = []

    for e in reads:
        summary = e.get("tool_input_summary") or {}
        if not isinstance(summary, dict):
            summary = {}
        file_path = summary.get("file_path")
        offset_val = summary.get("offset", "None")
        limit_val = summary.get("limit", "None")
        offset_repr = "None" if offset_val is None else str(offset_val)
        limit_repr = "None" if limit_val is None else str(limit_val)
        tuple_key = f"{file_path}|{offset_repr}|{limit_repr}"

        epoch = e.get("_epoch")
        turn_index = _turn_index_for_epoch(turns, pre_events, epoch)

        slot = aggregate.setdefault(tuple_key, {"count": 0, "first_turn": turn_index, "last_turn": turn_index})
        slot["count"] += 1
        if turn_index < slot["first_turn"]:
            slot["first_turn"] = turn_index
        if turn_index > slot["last_turn"]:
            slot["last_turn"] = turn_index

        if file_path is not None:
            path_counts[file_path] = path_counts.get(file_path, 0) + 1
            is_whole_file = (
                (offset_val is None or offset_val == "None")
                and (limit_val is None or limit_val == "None")
            )
            if is_whole_file:
                whole_file_paths.append(file_path)

    repeat_reads = {k: v for k, v in aggregate.items() if v["count"] > 1}
    whole_file_reads_over_500_lines = sum(1 for p in whole_file_paths if path_counts.get(p, 0) >= 2)
    return repeat_reads, whole_file_reads_over_500_lines


def _build_skills_aggregate(pre_events: list[dict], turns: list[dict]) -> dict:
    skill_events = [e for e in pre_events if e.get("tool_name") == "Skill"]
    if not skill_events:
        return {
            "call_count": 0,
            "unique_skills": [],
            "first_invocation_ts": None,
            "first_invocation_turn_index": None,
        }

    skill_events_sorted = sorted(
        skill_events,
        key=lambda e: e.get("_epoch") if isinstance(e.get("_epoch"), (int, float)) else 0.0,
    )
    unique: set[str] = set()
    for e in skill_events:
        summary = e.get("tool_input_summary") or {}
        name = summary.get("skill") if isinstance(summary, dict) else None
        if isinstance(name, str) and name:
            unique.add(name)

    first = skill_events_sorted[0]
    first_ts = first.get("_ts")
    first_epoch = first.get("_epoch")
    first_turn_index = _skill_turn_index(turns, first_epoch)

    return {
        "call_count": len(skill_events),
        "unique_skills": sorted(unique),
        "first_invocation_ts": first_ts,
        "first_invocation_turn_index": first_turn_index,
    }


def _skill_turn_index(turns: list[dict], epoch) -> int | None:
    if not turns or not isinstance(epoch, (int, float)):
        return None
    starts: list[tuple[int, float]] = []
    for t in turns:
        s = t.get("started_epoch")
        if isinstance(s, (int, float)):
            starts.append((t.get("turn_index"), s))
    if not starts:
        return None
    starts.sort(key=lambda x: x[1])
    matched = None
    for idx, s in starts:
        if s <= epoch:
            matched = idx
        else:
            break
    return matched


def _aggregate_toolsearch(pre_events: list[dict], post_events: list[dict]) -> dict:
    pre_ts = [e for e in pre_events if e.get("tool_name") == "ToolSearch"]
    if not pre_ts:
        return {}
    pre_ts_sorted = sorted(
        pre_ts,
        key=lambda e: e.get("_epoch") if isinstance(e.get("_epoch"), (int, float)) else 0.0,
    )
    queries: list[str] = []
    for e in pre_ts_sorted:
        summary = e.get("tool_input_summary") or {}
        q = summary.get("query") if isinstance(summary, dict) else None
        if isinstance(q, str):
            queries.append(q)

    loaded: set[str] = set()
    for e in post_events:
        if e.get("tool_name") != "ToolSearch":
            continue
        names = e.get("toolsearch_tools_loaded")
        if isinstance(names, list):
            for n in names:
                if isinstance(n, str) and n:
                    loaded.add(n)
    return {
        "call_count": len(pre_ts),
        "queries": queries,
        "tools_loaded": sorted(loaded),
    }


def _compaction_summary(events):
    comp = [e for e in events if e.get("phase") == "compaction"]
    triggers = {}
    for e in comp:
        t = e.get("trigger") or "unknown"
        triggers[t] = triggers.get(t, 0) + 1
    return len(comp), triggers


def _notification_summary(events):
    notes = [e for e in events if e.get("phase") == "notification"]
    kinds = {}
    for e in notes:
        k = e.get("kind") or "other"
        kinds[k] = kinds.get(k, 0) + 1
    return len(notes), kinds, kinds.get("permission_request", 0)


def _churn_summary(pre_events):
    added = sum((e.get("lines_added") or 0) for e in pre_events)
    removed = sum((e.get("lines_removed") or 0) for e in pre_events)
    return added, removed


def _mcp_summary(pre_events):
    breakdown = {}
    for e in pre_events:
        srv = e.get("mcp_server")
        if srv:
            breakdown[srv] = breakdown.get(srv, 0) + 1
    return sum(breakdown.values()), breakdown


def _test_summary(post_events):
    runs = 0
    passed = 0
    failed = 0
    failed_runs = 0
    for e in post_events:
        t = e.get("test")
        if not isinstance(t, dict):
            continue
        runs += 1
        if isinstance(t.get("test_passed"), int):
            passed += t["test_passed"]
        if isinstance(t.get("test_failed"), int):
            failed += t["test_failed"]
        if t.get("test_outcome") == "failed":
            failed_runs += 1
    return runs, passed, failed, failed_runs


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
