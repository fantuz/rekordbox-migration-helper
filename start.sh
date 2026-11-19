#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
task_venv_python=.venv/bin/python
if [ ! -e .venv ] && [ ! -L .venv ]; then
  task_system_python=""
  for task_candidate in python3 python3.13 python3.14 python3.15; do
    if command -v "$task_candidate" >/dev/null 2>&1 && "$task_candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 13))' >/dev/null 2>&1; then
      task_system_python=$task_candidate
      break
    fi
  done
  if [ -z "$task_system_python" ]; then
    printf '%s\n' 'Library Workbench requires Python 3.13 or newer. Install a supported Python and its venv package, or use the Linux portable package with Python included.' >&2
    exit 1
  fi
  task_python_version=$("$task_system_python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  if ! "$task_system_python" -m venv .venv; then
    printf 'Could not complete the virtual environment. On Debian/Ubuntu, install python%s-venv for this interpreter and run ./start.sh again.\n' "$task_python_version" >&2
    exit 1
  fi
fi
if [ ! -x "$task_venv_python" ] || ! "$task_venv_python" -c 'import sys; from pathlib import Path; raise SystemExit(sys.prefix == sys.base_prefix or Path(sys.prefix).resolve() != Path(".venv").resolve())' >/dev/null 2>&1; then
  printf '%s\n' 'The existing .venv is incomplete or does not identify this virtual environment. Repair it with a supported Python before starting; its files have been preserved.' >&2
  exit 1
fi
task_python_version=$("$task_venv_python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if ! "$task_venv_python" -c 'import sys; raise SystemExit(sys.version_info < (3, 13))'; then
  printf 'The existing .venv uses Python %s; Library Workbench requires Python 3.13 or newer. Use a supported virtual environment or the Linux portable package. Its files have been preserved.\n' "$task_python_version" >&2
  exit 1
fi
# A failed Debian venv bootstrap can leave Python installed without pip.
# Repair that same environment before consulting the dependency fingerprint.
if ! "$task_venv_python" -m pip --version >/dev/null 2>&1; then
  printf '%s\n' 'Repairing pip in the existing virtual environment.'
  if ! "$task_venv_python" -m ensurepip --upgrade || ! "$task_venv_python" -m pip --version >/dev/null 2>&1; then
    printf 'pip is unavailable. On Debian/Ubuntu, install python%s-venv for this interpreter, then run ./.venv/bin/python -m ensurepip --upgrade and ./start.sh again. No system packages were installed automatically.\n' "$task_python_version" >&2
    exit 1
  fi
fi
task_requirements_digest=$("$task_venv_python" -c 'from hashlib import sha256; from pathlib import Path; print(sha256(Path("requirements.txt").read_bytes()).hexdigest())')
task_installed_digest=""
if [ -f .venv/requirements.sha256 ]; then
  task_installed_digest=$(cat .venv/requirements.sha256)
fi
if [ "$task_installed_digest" != "$task_requirements_digest" ]; then
  "$task_venv_python" -m pip install -r requirements.txt
  printf '%s\n' "$task_requirements_digest" > .venv/requirements.sha256
fi
exec "$task_venv_python" desktop_launcher.py "$@"
