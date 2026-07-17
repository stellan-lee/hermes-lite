#!/usr/bin/env bash
set -euo pipefail

if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python -m pytest "$@"
fi
if [[ -x venv/bin/python ]]; then
  exec venv/bin/python -m pytest "$@"
fi
exec python3 -m pytest "$@"
