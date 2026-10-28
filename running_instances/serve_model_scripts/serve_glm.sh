#!/usr/bin/env bash
# GLM-5.3-Flash-FP8 (unsloth). 1M context is the model default.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/_prelude.sh"

VLLM_ENV="VLLM_ENGINE_READY_TIMEOUT_S=3600" \
run_vllm vllm/vllm-openai:nightly unsloth/GLM-5.3-Flash-FP8 "${SERVED_NAME:-glm-5.3-flash}" \
  --kv-cache-dtype fp8 \
  --tool-call-parser glm47 \
  --enable-auto-tool-choice \
  --reasoning-parser glm47 \
  --override-generation-config '{"temperature":1.0,"top_p":1.0}'
