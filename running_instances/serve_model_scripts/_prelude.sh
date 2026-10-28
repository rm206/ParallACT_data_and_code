#!/usr/bin/env bash
# Shared prelude for serving a model with vLLM in docker on a GPU machine.
# Source this, then call run_vllm. Weights are cached in $HF_HOME (mounted into the
# container), so they download once.
#
#   PORT          host port to serve on (default 8000)
#   MAX_NUM_SEQS  vLLM --max-num-seqs (default 4)
#   TP            tensor-parallel size = number of GPUs to use (default 4)
#   HF_HOME       host Hugging Face cache (default ~/.cache/huggingface)
#   HF_TOKEN      passed through for gated repos
set -euo pipefail
PORT="${PORT:-8000}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-4}"
TP="${TP:-4}"
HF_CACHE="${HF_HOME:-$HOME/.cache/huggingface}"
mkdir -p "$HF_CACHE"

command -v docker >/dev/null || { echo "FATAL: docker not found" >&2; exit 2; }

# run_vllm <image> <hf_model> <served_name> [extra vllm flags...]
# Extra per-model env vars via VLLM_ENV="K=V K2=V2" in the caller's environment.
run_vllm () {
  local img="$1" model="$2" served="$3"; shift 3
  local envflags=()
  if [[ -n "${VLLM_ENV:-}" ]]; then for kv in $VLLM_ENV; do envflags+=(-e "$kv"); done; fi
  [[ -n "${HF_TOKEN:-}" ]] && envflags+=(-e "HF_TOKEN=$HF_TOKEN")
  echo ">> serving '$served' ($model) on 0.0.0.0:$PORT  tp=$TP  max-num-seqs=$MAX_NUM_SEQS" >&2
  set -x
  docker run --rm --gpus all --ipc=host \
    -p "$PORT:$PORT" \
    -v "$HF_CACHE:/root/.cache/huggingface" \
    "${envflags[@]}" \
    --entrypoint vllm "$img" \
    serve "$model" \
      --host 0.0.0.0 --port "$PORT" \
      --served-model-name "$served" \
      --max-num-seqs "$MAX_NUM_SEQS" \
      --tensor-parallel-size "$TP" \
      "$@"
}
