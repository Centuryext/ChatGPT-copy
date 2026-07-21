#!/usr/bin/env bash
# Launch the local LLM as an OpenAI-compatible server on one of your 5090s.
# Requires: pip install vllm   (in a separate env with CUDA).
#
# Pick the GPU with CUDA_VISIBLE_DEVICES (0 = first 5090).
# Qwen2.5-14B is a good quality/latency balance for phone dialog. For lowest
# latency / more concurrency, use meta-llama/Llama-3.1-8B-Instruct instead.
set -euo pipefail

export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
MODEL=${LLM_MODEL:-Qwen/Qwen2.5-14B-Instruct}

vllm serve "$MODEL" \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --enable-chunked-prefill \
  --disable-log-requests

# Scale-out: run this again on CUDA_VISIBLE_DEVICES=1,2 (other 5090s) or the 3090s
# on ports 8001/8002 and put a load balancer in front for many concurrent calls.
