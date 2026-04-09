#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
if [[ -x ".venv/bin/mousekb" ]]; then
  exec ".venv/bin/mousekb" quick-capture
fi

exec uv run mousekb quick-capture
