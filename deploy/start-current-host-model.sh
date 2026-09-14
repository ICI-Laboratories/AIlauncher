#!/bin/bash
# Current NVIDIA host; adapt paths and device UUIDs before using on another host.
set -euo pipefail
export CUDA_VISIBLE_DEVICES=GPU-986b5314-77d6-6659-236a-6a76dbe59619,GPU-5e267c9b-8b94-c94e-e2df-c6fdfec69111
exec /home/cite/llama.cpp/build-cuda/bin/llama-server \
  --model /home/cite/models/Qwen3.8-27B/Qwen3.8-27B-Q4_K_M.gguf \
  --mmproj /home/cite/models/Qwen3.8-27B/mmproj-Qwen3.8-27B-BF16.gguf \
  --alias qwen-local \
  --device CUDA0,CUDA1 --split-mode layer --tensor-split 2,1 --n-gpu-layers 99 \
  --ctx-size 32768 --parallel 4 --kv-unified --kv-unified-per-slot 8192 \
  --image-min-tokens 1024 --image-max-tokens 4096 \
  --flash-attn on --threads 12 \
  --host 127.0.0.1 --port 8080 --cors-origins localhost \
  --jinja --chat-template-kwargs '{"enable_thinking":false}' \
  --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0.0 --presence-penalty 1.5
