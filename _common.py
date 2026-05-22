import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


SCHEMA_VERSION = 2

RUNS_DIR = Path(os.path.expanduser("~/.claude/runs"))
EVENTS_DIR = RUNS_DIR / "events"
ARTIFACTS_DIR = RUNS_DIR
SESSIONS_DIR = RUNS_DIR / "sessions"
PROMPTS_DIR = RUNS_DIR / "prompts"

for d in (RUNS_DIR, EVENTS_DIR, SESSIONS_DIR, PROMPTS_DIR):
    d.mkdir(parents=True, exist_ok=True)


def read_stdin_json():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except Exception as e:
        return {"_parse_error": str(e), "_raw": raw if "raw" in locals() else ""}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def append_event(session_id, event):
    if not session_id:
        session_id = "unknown"
    path = EVENTS_DIR / f"{session_id}.jsonl"
    event["_ts"] = now_iso()
    event["_epoch"] = time.time()
    event["schema_version"] = SCHEMA_VERSION
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception as e:
        err = EVENTS_DIR / "_errors.log"
        with err.open("a", encoding="utf-8") as f:
            f.write(f"{now_iso()} append_event failed: {e}\n")


def read_events(session_id):
    path = EVENTS_DIR / f"{session_id}.jsonl"
    if not path.exists():
        return []
    events = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def store_prompt(prompt_text: str) -> str:
    """Write full prompt to prompts dir, return short hash for event storage."""
    h = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
    path = PROMPTS_DIR / f"{h}.txt"
    if not path.exists():
        path.write_text(prompt_text, encoding="utf-8")
    return h


def read_subagent_watermark(session_id: str) -> float:
    path = EVENTS_DIR / f"{session_id}_watermark.txt"
    if not path.exists():
        return 0.0
    try:
        return float(path.read_text().strip())
    except Exception:
        return 0.0


def write_subagent_watermark(session_id: str, epoch: float) -> None:
    path = EVENTS_DIR / f"{session_id}_watermark.txt"
    path.write_text(str(epoch), encoding="utf-8")


def write_artifact(artifact):
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    task_id = artifact.get("task_id") or "notask"
    agent = artifact.get("agent") or "unknown"
    ts = artifact.get("timestamp_end") or now_iso()
    suffix = ts.replace(":", "").replace("-", "").replace(".", "")[:15]
    fname = f"{date}_{task_id}_{agent}_{suffix}.json"
    path = ARTIFACTS_DIR / fname
    with path.open("w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, default=str)
    return path


def write_session_rollup(session_id, rollup):
    path = SESSIONS_DIR / f"{session_id}.json"
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(rollup, f, indent=2, default=str)
    os.replace(tmp, path)
    return path


def _agent_map_path(session_id: str) -> Path:
    sid = session_id or "unknown"
    return EVENTS_DIR / f"{sid}_agent_map.json"


def _agent_map_lock_path(session_id: str) -> Path:
    sid = session_id or "unknown"
    return EVENTS_DIR / f"{sid}_agent_map.json.lock"


def read_agent_map(session_id: str) -> dict:
    path = _agent_map_path(session_id)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def write_agent_map(session_id: str, data: dict) -> None:
    path = _agent_map_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


class _AgentMapLock:
    def __init__(self, session_id: str, retries: int = 5, backoff: float = 0.05):
        self.session_id = session_id
        self.retries = retries
        self.backoff = backoff
        self._fp = None
        self._mode = None
        self._sentinel = None

    def __enter__(self):
        self._acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()
        return False

    def _acquire(self):
        try:
            import fcntl
            self._mode = "fcntl"
            path = _agent_map_lock_path(self.session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fp = path.open("a+")
            for _ in range(self.retries):
                try:
                    fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return
                except OSError:
                    time.sleep(self.backoff)
            try:
                fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX)
            except OSError:
                pass
            return
        except ImportError:
            pass
        try:
            import msvcrt
            self._mode = "msvcrt"
            path = _agent_map_lock_path(self.session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fp = path.open("a+b")
            for _ in range(self.retries):
                try:
                    msvcrt.locking(self._fp.fileno(), msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    time.sleep(self.backoff)
            try:
                msvcrt.locking(self._fp.fileno(), msvcrt.LK_LOCK, 1)
            except OSError:
                pass
            return
        except ImportError:
            pass
        self._mode = "sentinel"
        self._sentinel = _agent_map_lock_path(self.session_id)
        self._sentinel.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(self.retries):
            try:
                fd = os.open(str(self._sentinel), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return
            except FileExistsError:
                time.sleep(self.backoff)

    def _release(self):
        if self._mode == "fcntl" and self._fp is not None:
            try:
                import fcntl
                fcntl.flock(self._fp.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._fp.close()
            except Exception:
                pass
            return
        if self._mode == "msvcrt" and self._fp is not None:
            try:
                import msvcrt
                self._fp.seek(0)
                msvcrt.locking(self._fp.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            try:
                self._fp.close()
            except Exception:
                pass
            return
        if self._mode == "sentinel" and self._sentinel is not None:
            try:
                os.remove(str(self._sentinel))
            except Exception:
                pass


def update_agent_map(session_id: str, fn: Callable[[dict], "dict | None"]) -> dict:
    with _AgentMapLock(session_id):
        data = read_agent_map(session_id)
        result = fn(data)
        new_data = result if isinstance(result, dict) else data
        write_agent_map(session_id, new_data)
        return new_data