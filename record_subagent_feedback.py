import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ARTIFACTS_DIR, append_event, now_iso


VALID_OUTCOMES = {"accepted", "accepted_with_edits", "rejected", "revised", "retried", "superseded"}


def find_artifact(session_id: str, agent: str, task_id: str | None):
    candidates = []
    for p in ARTIFACTS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("session_id") != session_id:
            continue
        if agent and data.get("agent") != agent:
            continue
        if task_id and data.get("task_id") != task_id:
            continue
        candidates.append((p, data))
    if not candidates:
        return None, None
    candidates.sort(key=lambda t: t[1].get("timestamp_end") or "", reverse=True)
    return candidates[0]


def main():
    ap = argparse.ArgumentParser(
        description="Attach orchestrator-issued feedback to the most recent subagent artifact."
    )
    ap.add_argument("--session", required=True)
    ap.add_argument("--agent", required=True, help="Subagent name, e.g. implementer")
    ap.add_argument("--task-id", default=None, help="Optional task id or description to disambiguate")
    ap.add_argument(
        "--outcome",
        required=True,
        choices=sorted(VALID_OUTCOMES),
    )
    ap.add_argument("--reason", default="", help="Short rejection or revision reason")
    ap.add_argument("--revisions", type=int, default=0)
    ap.add_argument("--handoff-notes", default="")
    args = ap.parse_args()

    path, data = find_artifact(args.session, args.agent, args.task_id)
    if path is None:
        append_event(args.session, {
            "phase": "subagent_feedback",
            "kind": "artifact_not_found",
            "agent": args.agent,
            "task_id": args.task_id,
            "outcome": args.outcome,
            "reason": args.reason,
            "revisions": args.revisions,
            "handoff_notes": args.handoff_notes,
            "timestamp": now_iso(),
        })
        sys.stderr.write(
            f"No artifact found for session={args.session} agent={args.agent} task_id={args.task_id}\n"
        )
        return 1

    data["outcome"] = args.outcome
    data["rejection_reason"] = args.reason if args.outcome in ("rejected", "revised", "retried") else data.get("rejection_reason", "")
    data["revision_count"] = int(args.revisions)
    data["handoff_notes"] = args.handoff_notes
    data["feedback_recorded_at"] = now_iso()

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)

    append_event(args.session, {
        "phase": "subagent_feedback",
        "artifact": path.name,
        "agent": args.agent,
        "task_id": args.task_id,
        "outcome": args.outcome,
        "reason": args.reason,
        "revisions": args.revisions,
        "handoff_notes": args.handoff_notes,
        "timestamp": now_iso(),
    })

    print(path.name)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        sys.stderr.write(f"record_subagent_feedback error: {e}\n")
        sys.exit(1)
