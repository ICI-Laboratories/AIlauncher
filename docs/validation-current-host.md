# Current host validation — 2026-09-14 UTC

The deployment runs Qwen3.8-27B Q4_K_M with its BF16 vision projector on a
3090 24 GB and a 4070 SUPER 12 GB. llama.cpp revision: `67672dc5b`.
The host startup configuration is recorded in `deploy/start-current-host-model.sh`.
The optional CUDA/ROCm containers were configuration-validated only; the host
engine was used for these live measurements. No AMD hardware was available.

- Local suite: 51 tests passed, including per-app fairness, bounded queue,
  cancellation, disconnects, streaming cleanup and payload validation.
- Live test from a container attached **only** to `llm-apps`: authenticated
  readiness succeeded; missing-key requests returned 401; direct backend bridge
  access was blocked.
- Four different apps submitted short technical prompts with distinct system
  markers. All four markers were respected. 519 output tokens completed in
  7.26 seconds, approximately 71.5 aggregate output tokens/second including
  prompt processing. Individual latency: 6.58–7.26 seconds. This small smoke
  measurement is not a throughput guarantee for long contexts or images.
- Native image content: a generated red PNG was identified as `Red`.
- Native JSON schema: returned `{"voltage":12}` with no extra properties.
- Native SSE: first content arrived after 0.31 seconds. Closing the stream
  produced gateway status 499 and a llama.cpp cancellation/released-slot log;
  gateway active and queued counters returned to zero.
- Requests for 30,000 output tokens returned 422 against the 2,048-token cap.
- Loaded GPU memory after tests: 14,944 MiB on 3090 and 7,485 MiB on 4070 SUPER;
  temperatures were 38°C and 36°C respectively. These are sampled values,
  not high-water marks under sustained load.

Repeat the opt-in `deploy/validate-live.py` in an isolated app-network container
with the private test-key mount. Do not publish credentials. Long-context,
long-duration and mixed vision load testing is still needed before increasing
concurrency or making latency commitments. Applications requesting outputs
larger than 2,048 tokens need configuration changes or chunked generation.
