#!/usr/bin/env bash
# Download FABind+ and FlashBind checkpoints into src/FlashBind/ (not stored in git).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if ! python3 -c "import huggingface_hub" 2>/dev/null; then
  echo "Installing huggingface_hub..."
  python3 -m pip install -q huggingface_hub
fi

exec python3 scripts/setup/download_flashbind_assets.py "$@"
