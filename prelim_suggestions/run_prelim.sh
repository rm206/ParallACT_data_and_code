#!/usr/bin/env bash
# Waits for the vLLM server at VLLM_BASE_URL, then runs the resumable stage
# (python -m suggest.run --target N).
#
#   ./run_prelim.sh 1          # try it: 1 candidate
#   ./run_prelim.sh 5          # extends the same candidate set to 5
#   CONCURRENCY=8 ./run_prelim.sh 100
#
# Serve the model first:
#   bash ../running_instances/serve_model_scripts/serve_prelim.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$HERE"

TARGET="${1:-${TARGET:-}}"
[ -n "$TARGET" ] || { echo "usage: $0 <target> [concurrency]   (e.g. $0 5)" >&2; exit 2; }
CONCURRENCY="${2:-${CONCURRENCY:-4}}"

export VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen3.8-27B-FP8}"
export VLLM_BASE_URL="${VLLM_BASE_URL:-http://localhost:8000/v1}"

server_up () { curl -fsS "${VLLM_BASE_URL}/models" >/dev/null 2>&1; }

if ! server_up; then
  echo "waiting for the model server at ${VLLM_BASE_URL} ..."
  for _ in $(seq 1 600); do        # up to ~20 min
    server_up && break
    sleep 2
  done
  server_up || { echo "no server at ${VLLM_BASE_URL} (start serve_prelim.sh, or set VLLM_BASE_URL)" >&2; exit 1; }
fi
echo "server ready at ${VLLM_BASE_URL} (model ${VLLM_MODEL})"

echo "running stage: --target ${TARGET} --concurrency ${CONCURRENCY}"
exec uv run --project .. python -m suggest.run --target "$TARGET" --concurrency "$CONCURRENCY"
