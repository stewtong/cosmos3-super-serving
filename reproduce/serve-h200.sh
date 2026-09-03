#!/usr/bin/env bash
# Compatibility wrapper for the measured full-node H200 profile.
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
args=(serve --platform h200 --profile latency)
if [[ "${GUARDRAILS:-0}" == "1" ]]; then
  args+=(--guardrails)
fi
if [[ -n "${HF_CACHE_DIR:-}" ]]; then
  args+=(--cache-dir "$HF_CACHE_DIR")
fi
if [[ -n "${PORT:-}" ]]; then
  args+=(--port "$PORT")
fi
if [[ -n "${STARTUP_TIMEOUT:-}" ]]; then
  args+=(--startup-timeout "$STARTUP_TIMEOUT")
fi
exec "$repo_dir/bin/cosmos3-super" "${args[@]}" "$@"
