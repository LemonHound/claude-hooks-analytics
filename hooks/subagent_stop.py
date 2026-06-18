import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    SCHEMA_VERSION,
    append_event,
    now_iso,
    read_agent_map,
    read_events,
    read_stdin_json,
    read_subagent_watermark,
    update_agent_map,
    write_artifact,
    write_subagent_watermark,
)
from _transcript import read_transcript_intent, read_transcript_usage


def _resolve_attribution(
    events: list[dict],
    payload: dict,
    sidecar: dict | None,
) -> dict:
    raw_agent = payload.get("agent_type") or payload.get("agentType")
    if raw_agent not in (None, ""):
        return {
            "agent": raw_agent,
            "source": "payload",
            "consumed_tool_use_id": None,
            "requested_agent": None,
            "requested_prompt_hash": None,
        }

    sidecar_map = sidecar if isinstance(sidecar, dict) else {}
    payload_tid = payload.get("tool_use_id") or payload.get("toolUseId")
    if payload_tid and payload_tid in sidecar_map:
        entry = sidecar_map.get(payload_tid) or {}
        return {
            "agent": entry.get("agent_type") or "unknown",
            "source": "sidecar_by_id",
            "consumed_tool_use_id": payload_tid,
            "requested_agent": entry.get("agent_type"),
            "requested_prompt_hash": entry.get("prompt_hash"),
        }

    epochs = [e.get("_epoch") for e in events if isinstance(e.get("_epoch"), (int, float))]
    last_event_epoch = max(epochs) if epochs else None
    if sidecar_map and last_event_epoch is not None:
        candidates = [
            (tid, entry)
            for tid, entry in sidecar_map.items()
            if isinstance(entry, dict)
            and isinstance(entry.get("started_epoch"), (int, float))
            and entry.get("started_epoch") <= last_event_epoch
        ]
        if candidates:
            tid, entry = max(candidates, key=lambda item: item[1].get("started_epoch") or 0.0)
            return {
                "agent": entry.get("agent_type") or "unknown",
                "source": "sidecar_by_proximity",
                "consumed_tool_use_id": tid,
                "requested_agent": entry.get("agent_type"),
                "requested_prompt_hash": entry.get("prompt_hash"),
            }

    transcript_hint = _last_agent_from_events(events)
    if transcript_hint:
        return {
            "agent": transcript_hint,
            "source": "transcript",
            "consumed_tool_use_id": None,
            "requested_agent": None,
            "requested_prompt_hash": None,
        }

    return {
        "agent": "unknown",
        "source": "unknown",
        "consumed_tool_use_id": None,
        "requested_agent": None,
        "requested_prompt_hash": None,
    }


def build_artifact(
    events: list[dict],
    payload: dict,
    transcript_path: str | None,
    sidecar: dict | None,
    now_fn: Callable[[], str] = now_iso,
) -> dict:
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"

    attribution = _resolve_attribution(events, payload, sidecar)
    agent = attribution["agent"]
    agent_attribution_source = attribution["source"]
    requested_agent = attribution["requested_agent"]
    requested_prompt_hash = attribution["requested_prompt_hash"]
    consumed_tool_use_id = attribution["consumed_tool_use_id"]
    agent_id = payload.get("agent_id") or payload.get("agentId")
    task_id = (
        payload.get("task_id")
        or payload.get("taskId")
        or _first_task_description(events)
        or "notask"
    )

    tool_events = [e for e in events if e.get("phase") == "pre_tool"]
    post_events = [e for e in events if e.get("phase") == "post_tool"]

    transcript_usage = read_transcript_usage(transcript_path) if transcript_path else None

    if transcript_usage:
        input_tokens = transcript_usage["input_tokens"]
        output_tokens = transcript_usage["output_tokens"]
        cache_read = transcript_usage["cache_read_input_tokens"]
        cache_creation = transcript_usage["cache_creation_input_tokens"]
    else:
        input_tokens = sum((e.get("input_tokens") or 0) for e in post_events)
        output_tokens = sum((e.get("output_tokens") or 0) for e in post_events)
        cache_read = sum((e.get("cache_read_tokens") or 0) for e in post_events)
        cache_creation = sum((e.get("cache_creation_tokens") or 0) for e in post_events)

    error_count = sum(1 for e in post_events if e.get("is_error"))
    model = _dominant_model(post_events)

    files_read = sorted({
        (e.get("tool_input_summary") or {}).get("file_path")
        for e in tool_events
        if e.get("tool_name") == "Read"
    } - {None})
    files_written = sorted({
        (e.get("tool_input_summary") or {}).get("file_path")
        for e in tool_events
        if e.get("tool_name") in ("Write", "Edit", "MultiEdit", "NotebookEdit")
    } - {None})
    routed_to_next = sorted({
        e.get("agent_type")
        for e in tool_events
        if e.get("tool_name") in ("Agent", "Task") and e.get("agent_type")
    })
    skills_loaded = sorted({
        (e.get("tool_input_summary") or {}).get("skill")
        for e in tool_events
        if e.get("tool_name") == "Skill"
    } - {None})

    first_ts = events[0].get("_ts") if events else now_fn()
    last_ts = events[-1].get("_ts") if events else now_fn()
    first_epoch = events[0].get("_epoch") if events else None
    last_epoch = events[-1].get("_epoch") if events else None
    wall_clock_seconds = round(last_epoch - first_epoch, 3) if first_epoch and last_epoch else None

    transcript_intent = read_transcript_intent(transcript_path)
    orchestrator_intent = (
        transcript_intent
        or _first_task_description(events)
        or ""
    )
    task_hint = transcript_intent if (agent_attribution_source != "payload" and transcript_intent) else ""

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "agent": agent,
        "agent_id": agent_id,
        "agent_attribution_source": agent_attribution_source,
        "requested_agent": requested_agent,
        "requested_prompt_hash": requested_prompt_hash,
        "_consumed_sidecar_tool_use_id": consumed_tool_use_id,
        "model": model,
        "task_id": task_id,
        "task_hint": task_hint,
        "timestamp_start": first_ts,
        "timestamp_end": last_ts,
        "wall_clock_seconds": wall_clock_seconds,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_creation,
        "stop_reason": payload.get("stop_reason") or "subagent_stop",
        "error_count": error_count,
        "skills_loaded": skills_loaded,
        "context_files_loaded": files_read,
        "files_written": files_written,
        "tool_call_count": len(tool_events),
        "tool_call_breakdown": _breakdown(tool_events),
        "orchestrator_intent": orchestrator_intent,
        "routed_to_next": routed_to_next,
        "handoff_notes": "",
        "outcome": _derive_outcome(error_count, files_written, len(tool_events)),
        "revision_count": 0,
        "rejection_reason": "",
    }


def _apply_sidecar_pop(tid: str):
    def _fn(m: dict):
        m.pop(tid, None)
        return m
    return _fn


def main():
    payload = read_stdin_json()
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"

    append_event(session_id, {"phase": "subagent_stop", "raw_payload": payload})

    all_events = read_events(session_id)

    watermark = read_subagent_watermark(session_id)
    events = [e for e in all_events if e.get("_epoch", 0) > watermark]

    if events:
        write_subagent_watermark(session_id, max(e.get("_epoch", 0) for e in events))

    transcript_path = payload.get("agent_transcript_path")
    sidecar = read_agent_map(session_id)
    artifact = build_artifact(events, payload, transcript_path, sidecar)
    consumed = artifact.pop("_consumed_sidecar_tool_use_id", None)
    if consumed:
        try:
            update_agent_map(session_id, _apply_sidecar_pop(consumed))
        except Exception:
            pass
    write_artifact(artifact)


def _derive_outcome(error_count: int, files_written: list, tool_call_count: int) -> str:
    if tool_call_count == 0:
        return "no_tools_called"
    if error_count > 0:
        return "completed_with_errors"
    return "completed"


def _last_agent_from_events(events):
    for e in reversed(events):
        if e.get("tool_name") in ("Agent", "Task") and e.get("agent_type"):
            return e["agent_type"]
    return None


def _first_task_description(events):
    for e in events:
        if e.get("tool_name") in ("Agent", "Task") and e.get("task_description"):
            return e["task_description"]
    return None


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


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
