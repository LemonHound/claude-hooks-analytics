import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

sys.path.insert(0, str(Path(__file__).parent))

from _text import normalize_text


_DIRECT_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _coerce_path(path):
    if path is None:
        return None
    if isinstance(path, Path):
        return path
    if isinstance(path, str):
        if not path:
            return None
        return Path(path)
    return None


def _parse_epoch(ts):
    if not isinstance(ts, str) or not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, OSError):
        return None


def _iter_lines(path):
    p = _coerce_path(path)
    if p is None:
        return
    try:
        f = p.open("r", encoding="utf-8")
    except (OSError, ValueError):
        return
    try:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                continue
    finally:
        try:
            f.close()
        except OSError:
            pass


def iter_assistant_messages(path) -> Iterator[dict]:
    for ev in _iter_lines(path):
        if not isinstance(ev, dict):
            continue
        msg = ev.get("message")
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue
        usage = msg.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        ts = ev.get("timestamp") if isinstance(ev.get("timestamp"), str) else None
        model = msg.get("model") if isinstance(msg.get("model"), str) else None
        yield {
            "ts": ts,
            "epoch": _parse_epoch(ts),
            "model": model,
            "usage": usage,
            "raw": msg,
        }


def _extract_message_totals(usage):
    has_direct = any(k in usage for k in _DIRECT_KEYS)
    if has_direct:
        return {k: int(usage.get(k) or 0) for k in _DIRECT_KEYS}
    iterations = usage.get("iterations")
    if not isinstance(iterations, list) or not iterations:
        return None
    totals = {k: 0 for k in _DIRECT_KEYS}
    saw_value = False
    for it in iterations:
        if not isinstance(it, dict):
            continue
        for k in _DIRECT_KEYS:
            v = it.get(k)
            if v:
                saw_value = True
            totals[k] += int(v or 0)
    if not saw_value:
        return None
    return totals


def read_transcript_usage(path) -> Optional[dict]:
    p = _coerce_path(path)
    if p is None:
        return None
    sums = {k: 0 for k in _DIRECT_KEYS}
    model_counts = {}
    model_first_seen = {}
    seen_index = 0
    any_usage = False
    for msg in iter_assistant_messages(p):
        usage = msg.get("usage") or {}
        totals = _extract_message_totals(usage)
        if totals is None:
            continue
        if not any(totals.values()):
            continue
        any_usage = True
        for k in _DIRECT_KEYS:
            sums[k] += totals[k]
        model = msg.get("model")
        if isinstance(model, str) and model:
            model_counts[model] = model_counts.get(model, 0) + 1
            if model not in model_first_seen:
                model_first_seen[model] = seen_index
                seen_index += 1
    if not any_usage:
        return None
    dominant_model = None
    if model_counts:
        dominant_model = min(
            model_counts.items(),
            key=lambda kv: (-kv[1], model_first_seen[kv[0]]),
        )[0]
    return {
        "input_tokens": sums["input_tokens"],
        "output_tokens": sums["output_tokens"],
        "cache_read_input_tokens": sums["cache_read_input_tokens"],
        "cache_creation_input_tokens": sums["cache_creation_input_tokens"],
        "dominant_model": dominant_model,
    }


def _extract_user_text(msg):
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            text = first.get("text")
            if isinstance(text, str):
                return text
    return None


def read_transcript_intent(path) -> Optional[str]:
    p = _coerce_path(path)
    if p is None:
        return None
    for ev in _iter_lines(p):
        if not isinstance(ev, dict):
            continue
        if ev.get("isCompactSummary") is True:
            continue
        msg = ev.get("message")
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        text = _extract_user_text(msg)
        if not isinstance(text, str):
            continue
        normalized = normalize_text(text).strip()
        if not normalized:
            continue
        return normalized[:300]
    return None
