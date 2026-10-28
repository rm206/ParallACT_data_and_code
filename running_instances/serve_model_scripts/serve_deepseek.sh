#!/usr/bin/env bash
# DeepSeek-V4-Flash-0731. 1M context is the model default (no flag).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/_prelude.sh"

run_vllm vllm/vllm-openai:v0.28.0 deepseek-ai/DeepSeek-V4-Flash-0731 "${SERVED_NAME:-deepseek-v4-flash}" \
  --trust-remote-code \
  --kv-cache-dtype fp8 \
  --block-size 256 \
  --enable-expert-parallel \
  --attention_config.indexer_kv_dtype mxfp4 \
  --moe-backend deep_gemm_mega_moe \
  --tokenizer-mode deepseek_v4 \
  --tool-call-parser deepseek_v4 \
  --enable-auto-tool-choice \
  --reasoning-parser deepseek_v4 \
  --reasoning-config '{"reasoning_parser":"deepseek_v4","reasoning_start_str":"","reasoning_end_str":""}' \
  --override-generation-config '{"temperature":1.0,"top_p":0.95}' \
  --speculative-config '{"method":"dspark","num_speculative_tokens":7,"draft_sample_method":"probabilistic"}'
