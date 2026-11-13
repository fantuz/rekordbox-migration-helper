#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
task_requirements_digest=$(.venv/bin/python -c 'from hashlib import sha256; from pathlib import Path; print(sha256(Path("requirements.txt").read_bytes()).hexdigest())')
task_installed_digest=""
if [ -f .venv/requirements.sha256 ]; then
  task_installed_digest=$(cat .venv/requirements.sha256)
fi
if [ "$task_installed_digest" != "$task_requirements_digest" ]; then
  .venv/bin/python -m pip install -r requirements.txt
  printf '%s\n' "$task_requirements_digest" > .venv/requirements.sha256
fi
exec .venv/bin/python desktop_launcher.py "$@"
