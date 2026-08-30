#!/usr/bin/env bash
# Serve the Cosmos3-Super generator tower on one eight-GPU B200 node.
set -euo pipefail

IMAGE_DIGEST="sha256:6d2630c7d637b699557573f2c3fee8df5d4d0cd718977aa22549ed6a6ef30587"
IMAGE="vllm/vllm-omni:cosmos3@${IMAGE_DIGEST}"
MODEL="nvidia/Cosmos3-Super"
MODEL_REVISION="e0262be9d8f7586bc24c069a2aed2b665bdff266"
PORT="${PORT:-8000}"
NAME="${NAME:-cosmos3-b200}"
HF_CACHE_DIR="${HF_CACHE_DIR:-$HOME/.cache/huggingface}"
GUARDRAILS="${GUARDRAILS:-0}"

server_flags=(--cfg-parallel-size 2 --ulysses-degree 4 --use-hsdp --hsdp-shard-size 8 --init-timeout 1800)
docker_env=(-e VLLM_OMNI_VIDEO_SYNC_TIMEOUT=5400)
if [[ "$GUARDRAILS" == "1" ]]; then
  : "${HF_TOKEN:?GUARDRAILS=1 requires HF_TOKEN after accepting the guardrail repository terms}"
  docker_env+=(-e HF_TOKEN -e HF_HUB_DISABLE_XET=1)
else
  server_flags+=(--no-guardrails)
fi

num_gpus=$(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null | wc -l | tr -d ' ')
if [[ "${num_gpus:-0}" != "8" ]]; then
  echo "expected 8 GPUs, found ${num_gpus:-none}; refusing to start" >&2
  exit 1
fi
mkdir -p "$HF_CACHE_DIR"

exec docker run -d --name "$NAME" --gpus all --ipc=host --shm-size 32g \
  --ulimit nofile=1048576:1048576 \
  -v "$HF_CACHE_DIR":/root/.cache/huggingface \
  -p "127.0.0.1:${PORT}":8000 \
  "${docker_env[@]}" \
  "$IMAGE" \
  vllm serve "$MODEL" --revision "$MODEL_REVISION" \
    --omni --host 0.0.0.0 --port 8000 "${server_flags[@]}"
