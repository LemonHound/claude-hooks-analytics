import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import append_event, now_iso, read_stdin_json


CONFLICT_MARKERS = ("<<<<<<< ", "=======", ">>>>>>> ")
TEXT_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".scala", ".rb", ".php",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".swift",
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    ".md", ".mdx", ".rst", ".txt",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".xml", ".svg", ".sql", ".graphql", ".gql",
    ".tf", ".tfvars", ".hcl", ".dockerfile",
}


def main():
    payload = read_stdin_json()
    session_id = payload.get("session_id") or payload.get("sessionId") or "unknown"
    tool_name = payload.get("tool_name") or payload.get("toolName") or ""
    if tool_name not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return 0

    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_input, dict):
        return 0

    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return 0

    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return 0

    if p.suffix.lower() not in TEXT_EXTS and p.name.lower() not in {"dockerfile", "makefile"}:
        return 0

    try:
        size = p.stat().st_size
    except OSError:
        return 0
    if size > 2 * 1024 * 1024:
        return 0

    try:
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            hits = []
            for i, line in enumerate(f, start=1):
                for marker in CONFLICT_MARKERS:
                    if line.startswith(marker):
                        hits.append((i, line.rstrip("\n")[:120]))
                        break
                if len(hits) >= 5:
                    break
    except OSError:
        return 0

    if hits:
        append_event(session_id, {
            "phase": "red_flag",
            "kind": "conflict_marker",
            "tool_name": tool_name,
            "file_path": str(file_path),
            "hit_count": len(hits),
            "first_hit_line": hits[0][0],
            "timestamp": now_iso(),
        })
        msg_lines = [
            f"Conflict marker(s) detected in {file_path} after edit:",
        ]
        for ln, text in hits:
            msg_lines.append(f"  line {ln}: {text}")
        msg_lines.append(
            "Resolve these before continuing; do not commit or report success until the file is clean."
        )
        sys.stderr.write("\n".join(msg_lines) + "\n")
        return 2

    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        code = 0
    sys.exit(code or 0)
