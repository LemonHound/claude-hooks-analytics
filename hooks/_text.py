import re


_ZERO_WIDTH_TABLE = str.maketrans("", "", "​‌‍﻿")
_C0_DROP_TABLE = str.maketrans(
    "",
    "",
    "".join(chr(c) for c in range(0x00, 0x20) if c not in (0x09, 0x0A)),
)
_SPACE_RUN_RE = re.compile(r"(?<=\S) {2,}(?=\S)")


def _coerce(s):
    if isinstance(s, str):
        return s
    if isinstance(s, bytes):
        return s.decode("utf-8", errors="replace")
    return ""


def _scrub(s):
    if s.startswith("﻿"):
        s = s[1:]
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.translate(_ZERO_WIDTH_TABLE)
    s = s.translate(_C0_DROP_TABLE)
    return s


def normalize_text(s):
    out = _scrub(_coerce(s))
    if not out:
        return out
    return _SPACE_RUN_RE.sub(" ", out)


def normalize_command(s):
    return _scrub(_coerce(s))
