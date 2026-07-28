#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

check='import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 12) and tkinter.TkVersion >= 8.6 else 1)'
PY=
for candidate in python3.14 python3.13 python3.12 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "$check" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "No Python 3.12+ with a working Tk 8.6+ install was found." >&2
  echo "On macOS, the system python3 (/usr/bin/python3) uses Apple's outdated, buggy Tcl/Tk and will not work." >&2
  echo "Install a working one, e.g.: brew install python-tk@3.14" >&2
  echo "Or use the python.org installer: https://www.python.org/downloads/" >&2
  exit 1
fi

nohup "$PY" -m installer >/dev/null 2>&1 &
disown 2>/dev/null || true
