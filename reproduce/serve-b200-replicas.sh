#!/usr/bin/env bash
# Compatibility wrapper for an explicit B200 topology.
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
topology=${TOPOLOGY:-8x1}
args=(serve --platform b200 --topology "$topology")
if [[ "${GUARDRAILS:-0}" == "1" ]]; then
  args+=(--guardrails)
fi
if [[ -n "${HF_CACHE_DIR:-}" ]]; then
  args+=(--cache-dir "$HF_CACHE_DIR")
fi
if [[ -n "${BASE_PORT:-}" ]]; then
  args+=(--backend-base-port "$BASE_PORT")
fi
if [[ -n "${PORT:-}" ]]; then
  args+=(--port "$PORT")
fi
if [[ -n "${STARTUP_TIMEOUT:-}" ]]; then
  args+=(--startup-timeout "$STARTUP_TIMEOUT")
fi
exec "$repo_dir/bin/cosmos3-super" "${args[@]}" "$@"
