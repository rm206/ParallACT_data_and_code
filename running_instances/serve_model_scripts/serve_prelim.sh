#!/usr/bin/env bash
# Qwen3.8-27B-FP8, 1M context, used by prelim_suggestions.
# Served under its HF name, which is prelim_suggestions' default VLLM_MODEL.
MAX_NUM_SEQS="${MAX_NUM_SEQS:-8}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/_prelude.sh"

VLLM_ENV="VLLM_ALLOW_LONG_MAX_MODEL_LEN=1" \
run_vllm vllm/vllm-openai:nightly Qwen/Qwen3.8-27B-FP8 "${SERVED_NAME:-Qwen/Qwen3.8-27B-FP8}" \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_xml \
  --reasoning-parser qwen3 \
  --mm-encoder-tp-mode data \
  --hf-overrides '{"text_config": {"rope_parameters": {"mrope_interleaved": true, "mrope_section": [11, 11, 10], "rope_type": "yarn", "rope_theta": 10000000, "partial_rotary_factor": 0.25, "factor": 4.0, "original_max_position_embeddings": 262144}}}' \
  --max-model-len 1000000
