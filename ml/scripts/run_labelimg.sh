#!/usr/bin/env bash
# labelImg launcher — uses Python 3.12 (PyQt5 breaks on 3.14).
set -euo pipefail

ML_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ML_ROOT/.venv-labelimg"
REGRESSION="$ML_ROOT/tests/regression_set"
TH="${1:-th15}"

if [[ "$TH" != th15 && "$TH" != th16 ]]; then
  echo "Usage: $(basename "$0") [th15|th16]" >&2
  exit 1
fi

PYTHON312="${PYTHON312:-python3.12}"
if ! command -v "$PYTHON312" >/dev/null 2>&1; then
  echo "Python 3.12 required. Install: brew install python@3.12" >&2
  exit 1
fi

if [[ ! -x "$VENV/bin/labelImg" ]]; then
  echo "Creating $VENV ..."
  "$PYTHON312" -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip setuptools labelImg PyQt5 lxml
fi

cd "$REGRESSION"
exec "$VENV/bin/labelImg" "$TH/" "labels/$TH/"
