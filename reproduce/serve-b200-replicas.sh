#!/usr/bin/env bash
# Start one B200 topology. Topologies are measured in separate, sequential cells.
set -euo pipefail

IMAGE_DIGEST="sha256:6d2630c7d637b699557573f2c3fee8df5d4d0cd718977aa22549ed6a6ef30587"
IMAGE="vllm/vllm-omni:cosmos3@${IMAGE_DIGEST}"
MODEL="nvidia/Cosmos3-Super"
MODEL_REVISION="e0262be9d8f7586bc24c069a2aed2b665bdff266"
TOPOLOGY="${TOPOLOGY:-8x1}"
BASE_PORT="${BASE_PORT:-8100}"
NAME_PREFIX="${NAME_PREFIX:-cosmos3-${TOPOLOGY}}"
HF_CACHE_DIR="${HF_CACHE_DIR:-$HOME/.cache/huggingface}"
GUARDRAILS="${GUARDRAILS:-0}"
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-2400}"

case "$TOPOLOGY" in
  1x8) replicas=1; gpus_per_replica=8; layout=hybrid ;;
  2x4) replicas=2; gpus_per_replica=4; layout=tp4 ;;
  4x2) replicas=4; gpus_per_replica=2; layout=tp2 ;;
  8x1) replicas=8; gpus_per_replica=1; layout=tp1 ;;
  *) echo "TOPOLOGY must be 1x8, 2x4, 4x2, or 8x1" >&2; exit 2 ;;
esac

num_gpus=$(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null | wc -l | tr -d ' ')
if [[ "${num_gpus:-0}" != "8" ]]; then
  echo "expected 8 GPUs, found ${num_gpus:-none}; refusing to start" >&2
  exit 1
fi
if (( replicas * gpus_per_replica != 8 )); then
  echo "topology does not fill the node" >&2
  exit 2
fi
mkdir -p "$HF_CACHE_DIR"

docker_env=(-e VLLM_OMNI_VIDEO_SYNC_TIMEOUT=5400)
guard_flags=(--no-guardrails)
if [[ "$GUARDRAILS" == "1" ]]; then
  : "${HF_TOKEN:?GUARDRAILS=1 requires HF_TOKEN after accepting the guardrail repository terms}"
  docker_env+=(-e HF_TOKEN -e HF_HUB_DISABLE_XET=1)
  guard_flags=()
fi

wait_ready() {
  local name=$1 started now
  started=$(date +%s)
  while true; do
    if docker logs "$name" 2>&1 | grep -q "Application startup complete"; then
      return 0
    fi
    if [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || true)" != "true" ]]; then
      echo "${name} exited before readiness" >&2
      docker logs --tail 80 "$name" >&2 || true
      return 1
    fi
    now=$(date +%s)
    if (( now - started >= STARTUP_TIMEOUT )); then
      echo "${name} did not become ready within ${STARTUP_TIMEOUT} seconds" >&2
      return 1
    fi
    sleep 5
  done
}

start_replica() {
  local index=$1 port=$2 gpu_csv=$3
  local name="${NAME_PREFIX}-r${index}"
  local layout_flags=()
  case "$layout" in
    hybrid) layout_flags=(--cfg-parallel-size 2 --ulysses-degree 4 --use-hsdp --hsdp-shard-size 8) ;;
    tp4) layout_flags=(--tensor-parallel-size 4) ;;
    tp2) layout_flags=(--tensor-parallel-size 2) ;;
    tp1) layout_flags=(--tensor-parallel-size 1) ;;
  esac
  docker run -d --name "$name" --gpus "device=${gpu_csv}" --ipc=host --shm-size 32g \
    --ulimit nofile=1048576:1048576 \
    -v "$HF_CACHE_DIR":/root/.cache/huggingface \
    -p "127.0.0.1:${port}":8000 \
    "${docker_env[@]}" \
    "$IMAGE" \
    vllm serve "$MODEL" --revision "$MODEL_REVISION" \
      --omni --host 0.0.0.0 --port 8000 --init-timeout 1800 \
      "${layout_flags[@]}" "${guard_flags[@]}"
  wait_ready "$name"
  echo "replica ${index} ready on 127.0.0.1:${port} using GPUs ${gpu_csv}"
}

for ((index = 0; index < replicas; index++)); do
  first=$((index * gpus_per_replica))
  gpu_csv=""
  for ((offset = 0; offset < gpus_per_replica; offset++)); do
    gpu=$((first + offset))
    [[ -n "$gpu_csv" ]] && gpu_csv+=","
    gpu_csv+="$gpu"
  done
  start_replica "$index" "$((BASE_PORT + index))" "$gpu_csv"
done

echo "${TOPOLOGY} ready on ports ${BASE_PORT} through $((BASE_PORT + replicas - 1))"
echo "benchmark: python3 reproduce/benchmark.py --topology ${TOPOLOGY} --port ${BASE_PORT} --attempts 24"
