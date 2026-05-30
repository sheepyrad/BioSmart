#!/usr/bin/env bash
# Download FlashBind / FABind+ checkpoints into the cgflow submodule.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CGFLOW="${ROOT}/cgflow"

if [ ! -d "${CGFLOW}/scripts/setup" ]; then
  echo "cgflow submodule not initialized. Run: git submodule update --init --recursive" >&2
  exit 1
fi

exec "${CGFLOW}/scripts/setup/download_flashbind_assets.sh" "$@"
