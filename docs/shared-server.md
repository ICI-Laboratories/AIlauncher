# Shared LLM service for Docker applications

AIlauncher is the HTTP gateway. The default route uses the existing long-lived
`llama-server` for chat; optional OCR and embedding routes use their own llama.cpp
servers and admission queues. Applications use an OpenAI-compatible `/v1` URL and
separate API keys. The gateway never starts engines or loads/downloads models.

See [the auxiliary routing guide](auxiliary-gateway.md) for phase 2 configuration,
endpoint contracts and migration checks. Auxiliary routes remain disabled by default.

```text
Docker apps -> http://llm-gateway:8000/v1 -> shared gateway
                                          |-> chat llama-server
                                          |-> OCR llama-server (opt-in)
                                          |-> embeddings llama-server (opt-in)
```

The AMD project and its original deployment material remain in
[`legacy/lmserver`](../legacy/lmserver). New NVIDIA and AMD profiles use the same
HTTP gateway. The eight-GPU AMD profile is a deployment template, not a tested
hardware configuration.

## Current host engine

The default Compose deployment starts only the gateway. The existing host
`llama-server` stays at `127.0.0.1:8080` so the existing SSH chat remains usable.
A host forwarding service can expose that listener **only** at the gateway of a
dedicated backend Docker bridge, for example `172.30.81.1:8080`. Configure
`MODEL_BACKEND_URL=http://172.30.81.1:8080/v1` accordingly. There is no wildcard
host bind and no public gateway port.

`127.0.0.1` inside an ordinary container refers to that container. Neither
`localhost` nor `host.docker.internal` makes a host service bound to loopback
reachable automatically.

Before provisioning, inspect `ip route` and `docker network ls` / `docker network
inspect` to ensure the proposed subnet does not overlap existing networks. On a
host where this range is free:

```bash
docker network create --driver bridge --subnet 172.30.80.0/24 --gateway 172.30.80.1 --opt com.docker.network.bridge.name=br-llm-apps llm-apps
docker network create --driver bridge --internal --subnet 172.30.81.0/24 --gateway 172.30.81.1 --opt com.docker.network.bridge.name=br-llm-backend llm-backend
```

If the network already exists, reuse its inspected subnet and gateway. Keep the
forwarder limited to the selected bridge address and start it after Docker and
the inference service. Example forwarding command (run as a supervised systemd
service, not a terminal session):

```bash
/usr/bin/socat TCP4-LISTEN:8080,bind=172.30.81.1,reuseaddr,fork TCP4:127.0.0.1:8080
```

The gateway joins both networks. Application containers join only `llm-apps`;
inference containers join only `llm-backend`. Do not attach apps to the backend
network. Keep `llm-backend` internal to avoid an unnecessary outbound route.
Docker network separation alone does not protect a host listener: install a
persistent host INPUT firewall rule for destination `172.30.81.1`, TCP port
8080, allowing traffic from `br-llm-backend` and loopback and rejecting other
interfaces. Use a dedicated chain and boot service so Docker restarts or host
reboots do not silently remove that restriction. The relay should not start
unless those rules have been installed successfully.

Verify a direct call from an app-network-only container to
`172.30.81.1:8080` is rejected, while the authenticated gateway call succeeds.
The host firewall is required for the host-engine mode; Compose does not install
host firewall rules. Ensure the gateway URL, actual bridge names, and firewall
match if changing the example subnet. Host administrators and containers with
host networking or host-level privileges remain trusted.

## Gateway installation

From the repository root, copy `deploy/shared.example.env` to
`/etc/ailauncher/gateway.env`. Create the application-key file outside Git. Its
schema is a JSON object mapping a unique application identifier to its secret:

```json
{
  "sara": "replace-with-an-independent-random-secret",
  "slidercreator": "replace-with-another-independent-random-secret"
}
```

Generate real keys with `secrets.token_urlsafe(32)` and distribute only the
individual application's key to that application's secret store. The gateway
runs as UID 10001. A root-managed directory and readable single-file bind work
without making keys world-readable:

```bash
sudo install -d -m 0700 /etc/ailauncher
# After writing app-keys.json:
sudo chown 10001:10001 /etc/ailauncher/app-keys.json
sudo chmod 0400 /etc/ailauncher/app-keys.json
sudo chmod 0600 /etc/ailauncher/gateway.env
sudo docker compose --env-file /etc/ailauncher/gateway.env -f deploy/compose.shared.yml config --quiet
sudo docker compose --env-file /etc/ailauncher/gateway.env -f deploy/compose.shared.yml up -d --build gateway
```

Run one gateway process and one gateway replica: its admission counters are
in-memory. Additional Uvicorn workers or replicas multiply the limits rather
than coordinating them. Restart the gateway after changing keys or its
environment. Use a maintenance window to drain active streams before restarting.

The container health check uses public `/health` for process liveness. Check
`/ready` with a valid key separately to verify the model engine. `/metrics` is
also authenticated. Host administration is available at
`http://127.0.0.1:8009`; applications use Docker DNS, not that host URL.

## Connect an application

Add this to the application's Compose configuration, preserving its other
networks and services:

```yaml
services:
  app:
    environment:
      LLM_GATEWAY_BASE_URL: http://llm-gateway:8000/v1
      LLM_GATEWAY_API_KEY: ${APP_LLM_API_KEY}
      OPENAI_MODEL: qwen-local
    networks: [default, llm]
networks:
  llm:
    external: true
    name: llm-apps
```

Configure the model variable used by the application (`SARA_LLM_MODEL`,
`DEFAULT_LLM_MODEL`, etc.). Migrated apps use the canonical `LLM_GATEWAY_*`
variables and ignore their old direct-engine URLs. A plain HTTP call looks like:

```python
import os
import httpx

answer = httpx.post(
    os.environ["LLM_GATEWAY_BASE_URL"].rstrip("/") + "/chat/completions",
    headers={"Authorization": "Bearer " + os.environ["LLM_GATEWAY_API_KEY"]},
    json={"model": "qwen-local", "messages": [
        {"role": "system", "content": "Answer technical questions in Spanish."},
        {"role": "user", "content": "Explain a database index."},
    ], "max_tokens": 512},
    timeout=120,
)
answer.raise_for_status()
```

Existing names `sara-main` and `local-model` are aliases for the same loaded
model. `MODEL_ALIASES` controls accepted names (the first alias is the default); aliases do not load separate
weights. Unknown or disabled aliases now return 404; a model from the wrong
operation returns 409. There is no implicit fallback to the main model.
The JSON file `deploy/models.shared.json` documents the deployment;
it is **not** a config input to `shared_api` or the legacy `lmserv serve` command.

Applications must send their own system instructions and conversation history
on every request. Persist history in the application database under the correct
app/user/conversation identity. Do not treat an inference slot as a durable
conversation. Vision requests retain their OpenAI message content, including
image parts; successful interpretation depends on a compatible model and visual
projector. Streaming is relayed incrementally. The proxy preserves supported
chat request fields; model-dependent tools and structured outputs need an
end-to-end check for each application.

## Capacity and context

Default chat admission limits are four active requests for that engine, two per app, and
32 queued requests. Queue wait is limited to 60 seconds and upstream request
timeout to 300 seconds. These are initial configuration values; match
`MAX_INFLIGHT` to measured engine capacity. A full queue returns an overload
response instead of growing without bound. Clients should use bounded retries
with backoff and jitter; never loop immediately on overload.

`MAX_OUTPUT_TOKENS=2048` is the chat output budget. Higher requests are clamped and
receive `X-Tokens-Clamped: true`; conflicting output fields are rejected. Review apps requesting
16,384 or 30,000 output tokens before onboarding them. Long document generation
may need multiple requests, or a separately measured larger-context service.
`MAX_CONTEXT_TOKENS=8192` is the configured per-request context budget; the
engine's tokenizer and actual KV configuration determine final acceptance.
Input, output, image representations, and template overhead all consume context.
A request limit is not a reservation of memory for every pending conversation.

The optional engine profiles start with 32,768 total context tokens and four
parallel slots (a nominal 8,192 tokens per slot). Check the chosen llama.cpp
version's startup logs because context/KV behavior depends on version and flags.
Continuous batching combines work from active requests; it does not persist app
histories. Paged KV attention and Flash Attention address different engine
concerns; neither substitutes for application conversation ownership.

For each change, compare 1, 2, and 4 simultaneous calls with short prompts,
long prompts, and images. Record time to first token, full latency, aggregate
tokens/sec, queue rejections, and peak memory on each GPU. Confirm a cancelled
stream frees its admission slot. Validate independent system instructions in
simultaneous calls. Two GPUs increase available placement options, but PCIe
communication and unequal GPU speeds can reduce single-request performance.

## Optional NVIDIA container engine

The default deployment uses the already installed host engine. To replace it
with a container, install a compatible NVIDIA driver and NVIDIA Container
Toolkit, copy `deploy/nvidia.example.env` outside Git, set actual model and
projector paths, and select a tested image digest. Stop the host inference
service before starting another engine on the same GPUs:

```bash
sudo docker compose --env-file /etc/ailauncher/nvidia.env -f deploy/compose.shared.yml --profile nvidia up -d --build
```

Set `MODEL_BACKEND_URL=http://inference-nvidia:8080/v1`. CUDA device order must be
verified on that host. A `2,1` tensor split is only an initial ratio for 24 GB and
12 GB cards; reserve memory for KV cache, vision, and runtime buffers. The
container engine publishes no host port.

## Future eight-GPU AMD server

Copy `deploy/amd.example.env` outside Git. Confirm all eight GPUs are visible to
ROCm, and choose an image supporting the actual GPU architectures and model.
The official ROCm image tag is a default candidate; pin the validated digest.
Keep upstream AMD compatibility guidance with the server build record:

- [llama.cpp Docker images](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md)
- [AMD llama.cpp installation](https://rocm.docs.amd.com/projects/llama-cpp/en/latest/install/llama-cpp-install.html)

The profile passes `/dev/kfd` and `/dev/dri`, adds the host's numeric video/render
group IDs, and sets `HIP_VISIBLE_DEVICES=0,1,2,3,4,5,6,7`. Obtain real group IDs
with `getent group video render`. Do not assume the example IDs match. Set
`AMD_TENSOR_SPLIT` according to actual memory capacities; eight equal ratios
assume eight equal-capacity GPUs. Validate peer communication, thermals, power,
and workload measurements on the completed machine before raising limits.

```bash
sudo docker compose --env-file /etc/ailauncher/amd.env -f deploy/compose.shared.yml --profile amd up -d --build
```

Set `MODEL_BACKEND_URL=http://inference-amd:8080/v1`. Enable only one engine
profile in a deployment. The template assumes a vision model and its projector;
for a text-only model remove the `--mmproj` pair using a reviewed Compose
override. No eight-GPU AMD throughput or memory capacity has been validated by
this configuration alone.

## Recovery

Keep the previous host engine unit, model files, and environment backed up
before tuning. To stop the new gateway without touching host inference:

```bash
sudo docker compose --env-file /etc/ailauncher/gateway.env -f deploy/compose.shared.yml stop gateway
```

If a container engine fails, stop that profile before restoring the host engine.
Recheck authenticated `/ready` and a short chat plus image request before
reconnecting apps. Do not delete models, application histories, or source
archives as part of service rollback.

## Host provisioning helpers

After checking the reserved subnets, install `docker.io`, `docker-compose-v2`
and `socat`, then run `sudo deploy/setup-host-relay.sh`. It creates the two
bridges, a dedicated INPUT chain and the boot-enabled relay. It does not alter
SSH or flush other firewall chains. If reusing existing networks, inspect their
actual subnets and bridge names first; the helper does not migrate networks.

`sudo python3 deploy/create-app-keys.py` provisions the current host's keys and
writes individual client environment files under `/home/cite/local-ai/clients`
with private permissions. It preserves existing credentials on subsequent runs.
The helper assumes the local service owner is `cite`; adapt that explicit path
and user on another host. Do not commit these files or pass the admin key to apps.
Client files include canonical `LLM_GATEWAY_BASE_URL`/`LLM_GATEWAY_API_KEY` plus
standard SDK aliases pointing to the same gateway. Do not put these files in
browser bundles; the Bitácora desktop client accepts its credential in memory.

Rollback: stop the gateway with Compose, stop/disable `ailauncher-relay.service`,
and restore the backed-up host model startup script if engine settings changed.
Remove only the specific INPUT jump to `AILAUNCHER_RELAY` and its own chain if
retiring the relay. The original loopback model endpoint remains independent.
