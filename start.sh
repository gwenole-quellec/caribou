#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

# Create the virtual environment on first use.
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
fi

# Install UI dependencies on first use or when either requirements file changes.
requirements_hash="$(.venv/bin/python - <<'PY'
from hashlib import sha256
from pathlib import Path

fingerprint = sha256()
for name in ("requirements.txt", "requirements-ui.txt"):
    fingerprint.update(name.encode())
    fingerprint.update(Path(name).read_bytes())
print(fingerprint.hexdigest())
PY
)"
stamp=".venv/.caribou-requirements.sha256"
installed_hash=""
if [ -f "$stamp" ]; then
    installed_hash="$(cat "$stamp")"
fi

if [ "$requirements_hash" != "$installed_hash" ] || ! .venv/bin/python - <<'PY'
from importlib.metadata import PackageNotFoundError, version

try:
    major, minor = map(int, version("streamlit").split(".")[:2])
except (PackageNotFoundError, ValueError):
    raise SystemExit(1)

raise SystemExit(0 if (major, minor) >= (1, 40) and major < 2 else 1)
PY
then
    .venv/bin/python -m pip install -r requirements-ui.txt
    printf '%s\n' "$requirements_hash" > "$stamp"
fi

exec .venv/bin/streamlit run caribou.py "$@"
