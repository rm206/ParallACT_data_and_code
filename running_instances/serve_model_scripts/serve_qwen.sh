#!/usr/bin/env bash
# Qwen3.8-Flash-Next-FP8, 1M context.
# 1M context needs VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 + the rope hf-overrides + --max-model-len.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/_prelude.sh"

VLLM_ENV="VLLM_ALLOW_LONG_MAX_MODEL_LEN=1" \
run_vllm vllm/vllm-openai:nightly Qwen/Qwen3.8-Flash-Next-FP8 "${SERVED_NAME:-qwen3-flash-next}" \
  --gpu-memory-utilization 0.90 \
  --enable-prefix-caching \
  --no-enable-flashinfer-autotune \
  --kv-cache-dtype fp8 \
  --attention-config.indexer_kv_dtype fp8 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --override-generation-config '{"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0.0,"presence_penalty":0.0,"repetition_penalty":1.0}' \
  --speculative-config '{"method":"mtp","num_speculative_tokens":3}' \
  --hf-overrides '{"text_config": {"rope_parameters": {"mrope_interleaved": true, "mrope_section": [11, 11, 10], "rope_type": "yarn", "rope_theta": 10000000, "partial_rotary_factor": 0.25, "factor": 4.0, "original_max_position_embeddings": 262144}}}' \
  --max-model-len 1000000
