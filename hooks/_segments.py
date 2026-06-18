import re
import shlex
from typing import Literal

from _text import normalize_command


Shell = Literal["bash", "powershell"]


def parse_mcp_tool(tool_name):
    if not isinstance(tool_name, str) or not tool_name.startswith("mcp__"):
        return None, None
    parts = tool_name.split("__")
    if len(parts) < 3:
        return (parts[1] if len(parts) > 1 else None), None
    return parts[1], "__".join(parts[2:])


_BASH_CATEGORY_PATTERNS = [
    ("git", re.compile(r"^\s*(git|gh)\b")),
    ("test", re.compile(r"\b(pytest|jest|vitest|mocha|go\s+test|cargo\s+test|npm\s+test|yarn\s+test|pnpm\s+test|rspec|tox|nox|unittest)\b")),
    ("deploy", re.compile(r"\b(gcloud|aws|terraform|kubectl|helm|docker\s+push|cloud\s+run|fly\s+deploy|vercel|render|railway)\b")),
    ("build", re.compile(r"\b(npm\s+run\s+build|yarn\s+build|pnpm\s+build|make\b|cargo\s+build|go\s+build|tsc\b|webpack|vite\s+build|dotnet\s+build|dotnet\s+publish|msbuild)\b")),
    ("pkg", re.compile(r"\b(npm|yarn|pnpm|pip|uv|poetry|cargo|go\s+get|apt|brew)\s+(install|add|sync|upgrade|remove|uninstall)\b")),
    ("fs_mutate", re.compile(r"^\s*(rm|mv|cp|mkdir|rmdir|touch|ln|chmod|chown|sed\s+-i|truncate|tee)\b|^\s*find\b[^|;&]*\s-delete\b|^\s*xargs\b[^|;&]*\srm\b|(?:^|\s)>>?\s+\S|\btee(?:\s+-a)?\s+\S")),
    ("fs_read", re.compile(r"^\s*(ls|cat|head|tail|less|more|find|tree|stat|wc|du|df|file)\b")),
    ("net", re.compile(r"^\s*(curl|wget|ping|nslookup|dig|ssh|scp|rsync|http\b|httpie)\b")),
    ("shell_meta", re.compile(r"^\s*(cd|pwd|echo|printf|export|source|\.)\s")),
    ("python", re.compile(r"^\s*(python3?|uv\s+run|pipx|poetry\s+run|pytest)\b")),
    ("node", re.compile(r"^\s*(node|npx|tsx|ts-node|bun)\b")),
]


_POWERSHELL_CATEGORY_PATTERNS = [
    ("git", re.compile(r"^\s*(git|gh)\b", re.IGNORECASE)),
    ("test", re.compile(r"\b(pytest|Invoke-Pester)\b", re.IGNORECASE)),
    ("pkg", re.compile(r"\b(npm|yarn|pnpm|pip|uv|poetry|cargo)\s+(install|add|sync|upgrade|remove|uninstall)\b", re.IGNORECASE)),
    ("net", re.compile(r"\b(Invoke-WebRequest|Invoke-RestMethod|curl|wget)\b", re.IGNORECASE)),
    ("fs_mutate", re.compile(r"\b(Remove-Item|Move-Item|Copy-Item|Rename-Item|New-Item|Out-File|Set-Content|Add-Content|Clear-Content)\b", re.IGNORECASE)),
    ("fs_read", re.compile(r"\b(Get-[A-Za-z]+|Select-[A-Za-z]+)\b")),
    ("shell_meta", re.compile(r"^\s*(Set-Location|cd|pwd|Write-Host|Write-Output|echo)\b", re.IGNORECASE)),
    ("python", re.compile(r"^\s*(python3?|uv\s+run|pipx|poetry\s+run|pytest)\b", re.IGNORECASE)),
    ("node", re.compile(r"^\s*(node|npx|tsx|ts-node|bun)\b", re.IGNORECASE)),
]


_BASH_MUTATION_PATTERNS = [
    re.compile(r"^\s*rm\s+(?:-[rRfidv]+\s+)*(.+)$"),
    re.compile(r"^\s*mv\s+(?:-[fFniv]+\s+)*(\S+)\s+(\S+)"),
    re.compile(r"^\s*cp\s+(?:-[rRfiv]+\s+)*(\S+)\s+(\S+)"),
    re.compile(r"^\s*git\s+rm\s+(?:-[rfq]+\s+)*(.+)$"),
    re.compile(r"^\s*sed\s+-i\S*\s+\S+\s+(.+)$"),
    re.compile(r"^\s*touch\s+(.+)$"),
    re.compile(r"^\s*mkdir\s+(?:-[pv]+\s+)*(.+)$"),
]

_BASH_REDIRECT_RE = re.compile(r"(?:^|\s)(?:>>?|\btee(?:\s+-a)?)\s+([^\s|&;]+)")
_FIND_DELETE_RE = re.compile(r"^\s*find\s+(\S+)(?=.*-delete\b)")
_XARGS_RM_RE = re.compile(r"^\s*xargs\s+(?:-[a-zA-Z0-9]+\s+)*rm\s+(?:-[rRfidv]+\s+)*(.*)$")

_PS_MUTATION_PATTERNS = [
    re.compile(r"\b(?:Remove-Item|Move-Item|Copy-Item|Rename-Item|Out-File|Set-Content|Add-Content|Clear-Content)\b((?:\s+-[A-Za-z]+(?:\s+\S+)?)*\s+)(\S+)", re.IGNORECASE),
]
_PS_REDIRECT_RE = re.compile(r"(?:^|\s)>>?\s+([^\s|&;]+)")

_HEREDOC_OPENER_RE = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")


def _find_heredoc_opener(line):
    masked = _mask_quotes(line)
    for m in re.finditer(r"<<(-?)", masked):
        start = m.start()
        if start + 2 + (1 if m.group(1) else 0) >= len(line):
            continue
        rest_orig = line[m.end():]
        opener_match = re.match(r"\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", rest_orig)
        if not opener_match:
            continue
        return _HeredocMatch(
            dash=bool(m.group(1)),
            quote=opener_match.group(1),
            tag=opener_match.group(2),
            end=m.end() + opener_match.end(),
        )
    return None


class _HeredocMatch:
    __slots__ = ("dash", "quote", "tag", "end")

    def __init__(self, dash, quote, tag, end):
        self.dash = dash
        self.quote = quote
        self.tag = tag
        self.end = end


def _coerce_str(cmd):
    if isinstance(cmd, str):
        return cmd
    return ""


def _mask_quotes(s):
    out = []
    i = 0
    n = len(s)
    in_single = False
    in_double = False
    in_back = False
    while i < n:
        ch = s[i]
        if not in_single and not in_double and not in_back and ch == "\\" and i + 1 < n:
            out.append("\x00")
            out.append("\x00")
            i += 2
            continue
        if not in_double and not in_back and ch == "'":
            in_single = not in_single
            out.append(ch)
            i += 1
            continue
        if not in_single and not in_back and ch == '"':
            in_double = not in_double
            out.append(ch)
            i += 1
            continue
        if not in_single and not in_double and ch == "`":
            in_back = not in_back
            out.append(ch)
            i += 1
            continue
        if in_single or in_double or in_back:
            out.append("\x00")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _mask_subshells(cmd):
    masked_quotes = _mask_quotes(cmd)
    restore = {}
    result = []
    i = 0
    n = len(cmd)
    counter = 0
    while i < n:
        if i + 1 < n and masked_quotes[i] == "$" and masked_quotes[i + 1] == "(":
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if masked_quotes[j] == "(":
                    depth += 1
                elif masked_quotes[j] == ")":
                    depth -= 1
                if depth == 0:
                    break
                j += 1
            if depth == 0 and j < n:
                placeholder = f"__SUBSHELL_{counter}__"
                restore[placeholder] = cmd[i:j + 1]
                result.append(placeholder)
                counter += 1
                i = j + 1
                continue
        result.append(cmd[i])
        i += 1
    return "".join(result), restore


def _restore_subshells(s, restore):
    out = s
    for placeholder, original in restore.items():
        out = out.replace(placeholder, original)
    return out


def _strip_heredocs_for_split(cmd):
    out_lines = []
    lines = cmd.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _find_heredoc_opener(line)
        if not m:
            out_lines.append(line)
            i += 1
            continue
        dash = m.dash
        tag = m.tag
        out_lines.append(line)
        i += 1
        while i < len(lines):
            body_line = lines[i]
            check = body_line.lstrip("\t") if dash else body_line
            if check == tag:
                i += 1
                break
            i += 1
    return "\n".join(out_lines)


def _split_with_shlex(masked):
    try:
        lex = shlex.shlex(masked, posix=True, punctuation_chars="&|;")
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        raise
    segments = []
    current = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("&&", "||", ";", "|"):
            if current:
                segments.append(" ".join(current))
                current = []
            i += 1
            continue
        current.append(tok)
        i += 1
    if current:
        segments.append(" ".join(current))
    return segments


def _split_naive(masked):
    parts = []
    buf = []
    i = 0
    n = len(masked)
    while i < n:
        if i + 1 < n and masked[i:i + 2] in ("&&", "||"):
            parts.append("".join(buf))
            buf = []
            i += 2
            continue
        if masked[i] in (";", "|"):
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(masked[i])
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _split_masked(masked_cmd):
    parts = []
    buf = []
    i = 0
    n = len(masked_cmd)
    in_single = False
    in_double = False
    in_back = False
    while i < n:
        ch = masked_cmd[i]
        if not in_single and not in_double and not in_back and ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(masked_cmd[i + 1])
            i += 2
            continue
        if not in_double and not in_back and ch == "'":
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue
        if not in_single and not in_back and ch == '"':
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue
        if not in_single and not in_double and ch == "`":
            in_back = not in_back
            buf.append(ch)
            i += 1
            continue
        if not in_single and not in_double and not in_back:
            if i + 1 < n and masked_cmd[i:i + 2] in ("&&", "||"):
                parts.append("".join(buf))
                buf = []
                i += 2
                continue
            if ch in (";", "|"):
                parts.append("".join(buf))
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    if in_single or in_double or in_back:
        raise ValueError("unbalanced quotes")
    return [p.strip() for p in parts if p.strip()]


def split_segments(cmd):
    cmd = _coerce_str(cmd)
    if not cmd:
        return []
    stripped = _strip_heredocs_for_split(cmd)
    masked, restore = _mask_subshells(stripped)
    try:
        segments = _split_masked(masked)
    except ValueError:
        segments = _split_naive(masked)
    restored = [_restore_subshells(seg, restore) for seg in segments]
    return [s.strip() for s in restored if s.strip()]


def _classify_segment(seg, patterns):
    cats = []
    for label, pat in patterns:
        if pat.search(seg):
            if label not in cats:
                cats.append(label)
    return cats


def _union_with_meta_drop(per_seg):
    union = []
    for cats in per_seg:
        for c in cats:
            if c not in union:
                union.append(c)
    if "shell_meta" in union and len(union) > 1:
        union = [c for c in union if c != "shell_meta"]
    return union


def classify_bash(cmd):
    cmd = _coerce_str(cmd)
    if not cmd:
        return []
    segments = split_segments(cmd)
    per_seg = [_classify_segment(seg, _BASH_CATEGORY_PATTERNS) for seg in segments]
    return _union_with_meta_drop(per_seg)


def _classify_powershell_segment(seg):
    cats = _classify_segment(seg, _POWERSHELL_CATEGORY_PATTERNS)
    stripped = seg.lstrip()
    if stripped.startswith("&"):
        rest = stripped[1:].lstrip()
        target = _extract_call_target(rest)
        if target:
            low = target.lower()
            if low.endswith(".py"):
                if "python" not in cats:
                    cats.append("python")
            elif low.endswith("pytest.exe"):
                if "test" not in cats:
                    cats.append("test")
    return cats


def _extract_call_target(s):
    if not s:
        return ""
    if s.startswith('"'):
        end = s.find('"', 1)
        if end > 0:
            return s[1:end]
        return s[1:]
    if s.startswith("'"):
        end = s.find("'", 1)
        if end > 0:
            return s[1:end]
        return s[1:]
    parts = s.split(None, 1)
    return parts[0] if parts else ""


def classify_powershell(cmd):
    cmd = _coerce_str(cmd)
    if not cmd:
        return []
    segments = split_segments(cmd)
    per_seg = [_classify_powershell_segment(seg) for seg in segments]
    union = _union_with_meta_drop(per_seg)
    if not union:
        return ["other"]
    return union


def classify_segments(cmd, shell):
    cmd = _coerce_str(cmd)
    if not cmd:
        return []
    segments = split_segments(cmd)
    if shell == "powershell":
        return [_classify_powershell_segment(seg) for seg in segments]
    return [_classify_segment(seg, _BASH_CATEGORY_PATTERNS) for seg in segments]


def _split_args(s):
    try:
        return shlex.split(s, posix=True)
    except ValueError:
        return s.split()


def _split_args_preserve_backslash(s):
    try:
        return shlex.split(s, posix=False)
    except ValueError:
        return s.split()


def _clean_target(t):
    t = t.strip()
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        t = t[1:-1]
    return t


def _is_flag(t):
    return t.startswith("-")


def _extract_bash_targets_from_segment(seg, collected):
    for pat in _BASH_MUTATION_PATTERNS:
        m = pat.match(seg)
        if not m:
            continue
        for group in m.groups():
            if not group:
                continue
            for raw in _split_args(group):
                t = _clean_target(raw)
                if t and not _is_flag(t) and t not in ("&&", "||", ";", "|"):
                    if t not in collected:
                        collected.append(t)
        break

    fm = _FIND_DELETE_RE.match(seg)
    if fm:
        t = _clean_target(fm.group(1))
        if t and not _is_flag(t) and t not in collected:
            collected.append(t)

    xm = _XARGS_RM_RE.match(seg)
    if xm:
        rest = xm.group(1) or ""
        for raw in _split_args(rest):
            t = _clean_target(raw)
            if t and not _is_flag(t) and t not in collected:
                collected.append(t)

    for m in _BASH_REDIRECT_RE.finditer(seg):
        t = _clean_target(m.group(1))
        if t and not _is_flag(t) and t not in collected:
            collected.append(t)


def _extract_ps_targets_from_segment(seg, collected):
    cmdlet_re = re.compile(
        r"\b(Remove-Item|Move-Item|Copy-Item|Rename-Item|Out-File|Set-Content|Add-Content|Clear-Content)\b(.*)",
        re.IGNORECASE,
    )
    m = cmdlet_re.search(seg)
    if m:
        rest = m.group(2)
        tokens = _split_args_preserve_backslash(rest)
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.startswith("-"):
                low = tok.lower()
                if low in ("-path", "-literalpath", "-destination", "-newname", "-filepath"):
                    if i + 1 < len(tokens):
                        t = _clean_target(tokens[i + 1])
                        if t and not _is_flag(t) and t not in collected:
                            collected.append(t)
                        i += 2
                        continue
                if low in ("-recurse", "-force", "-confirm", "-whatif", "-verbose", "-passthru", "-append", "-noclobber"):
                    i += 1
                    continue
                i += 2
                continue
            t = _clean_target(tok)
            if t and t not in collected:
                collected.append(t)
            i += 1

    for rm in _PS_REDIRECT_RE.finditer(seg):
        t = _clean_target(rm.group(1))
        if t and not _is_flag(t) and t not in collected:
            collected.append(t)


def extract_mutation_targets(cmd, shell):
    cmd = _coerce_str(cmd)
    if not cmd:
        return []
    collected = []
    segments = split_segments(cmd)
    if shell == "powershell":
        for seg in segments:
            _extract_ps_targets_from_segment(seg, collected)
    else:
        for seg in segments:
            _extract_bash_targets_from_segment(seg, collected)
        for hd in extract_heredoc_segments(cmd):
            target = hd.get("redirect_target")
            if target and target not in collected:
                collected.append(target)
    unique_sorted = sorted(set(collected))
    return unique_sorted[:20]


def _detect_redirect_after_opener(line, opener_end):
    tail = line[opener_end:]
    masked_tail = _mask_quotes(tail)
    tee_match = re.search(r"\|\s*tee(?:\s+-a)?\s+([^\s|&;]+)", masked_tail)
    if tee_match:
        start = tee_match.start(1)
        end = tee_match.end(1)
        return _clean_target(tail[start:end])
    redir_match = re.search(r"(?:^|\s)>>?\s+([^\s|&;<>]+)", masked_tail)
    if redir_match:
        start = redir_match.start(1)
        end = redir_match.end(1)
        return _clean_target(tail[start:end])
    return None


def extract_heredoc_segments(cmd):
    cmd = _coerce_str(cmd)
    if not cmd:
        return []
    results = []
    lines = cmd.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _find_heredoc_opener(line)
        if not m:
            i += 1
            continue
        dash = m.dash
        quote = m.quote
        tag = m.tag
        is_quoted = quote in ("'", '"')
        opener_end = m.end
        redirect_target = _detect_redirect_after_opener(line, opener_end)
        body_lines = []
        j = i + 1
        closed = False
        while j < len(lines):
            body_line = lines[j]
            check = body_line.lstrip("\t") if dash else body_line
            if check == tag:
                closed = True
                break
            if dash:
                body_lines.append(body_line.lstrip("\t"))
            else:
                body_lines.append(body_line)
            j += 1
        body_raw = "\n".join(body_lines)
        if body_lines and (closed or j >= len(lines)):
            body_raw = body_raw + "\n"
        body = normalize_command(body_raw)
        results.append({
            "tag": tag,
            "body": body,
            "redirect_target": redirect_target,
            "is_quoted": is_quoted,
            "indent_stripped": dash,
        })
        if closed:
            i = j + 1
        else:
            i = j
    return results
