#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python 3.12+ is required but was not found. Install it from https://www.python.org/downloads/ and retry." >&2
  exit 1
fi
exec "$PY" -m installer
