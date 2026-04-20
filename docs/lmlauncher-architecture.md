# LMLauncher Gateway Architecture

## Objective

LMLauncher is evolving from a local `llama.cpp` server into a gateway that lets
researchers and small companies connect their existing AI-enabled applications to
local or self-hosted LLM infrastructure with minimal code changes.

The design target is:

- one stable URL for client applications
- multiple interchangeable model backends
- automatic capability-aware routing
- transparent fallback for structured outputs
- a cleaner path toward horizontal scaling

## Current architecture

The new base introduces three layers:

1. Gateway API
   Exposes a simple legacy `/chat` endpoint and an OpenAI-compatible
   `/v1/chat/completions` endpoint so existing applications can connect by only
   changing `base_url` and credentials.

2. Catalog and resolver
   A JSON catalog declares models, backends, aliases and advertised
   capabilities such as `structured_output`, `json_mode` and `tools`.

3. Backend runtimes
   Each backend is wrapped behind a runtime interface. The first supported
   runtimes are `llama_cpp` and `ollama`.

## Routing rule for structured outputs

When a request arrives with a `response_format` that requires structured
output:

1. LMLauncher checks the requested or default model.
2. If that model advertises the required capability, the request stays there.
3. If not, the resolver searches for another route in the catalog that
   satisfies the capability.
4. The request is transparently rerouted and the client keeps the same API
   surface.

This is the first concrete step toward the paper's main idea: users should not
have to know which model is best for each protocol-level feature.

## Example deployment modes

### Simple single-model mode

```bash
lmserv serve --backend llama_cpp --model models/main.gguf
```

### Gateway catalog mode

```bash
lmserv serve --catalog models.example.json
```

### Existing app using OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="changeme",
)

response = client.chat.completions.create(
    model="research-main",
    messages=[{"role": "user", "content": "Resume el experimento en JSON"}],
)
```

## Next engineering steps

- add real token streaming for every backend
- add a distributed registry and queue for multi-node scheduling
- add health scoring and weighted balancing across nodes
- formalize tool connectors over HTTP, MCP or local plugin contracts
- separate control plane and execution plane
- add observability: latency, queue depth, fallback rate and token throughput

## Notes for the paper

The codebase now has a clear research narrative:

- problem: local LLM deployment is fragmented across engines and protocols
- proposal: capability-aware gateway with protocol compatibility and transparent
  fallback
- contribution: a practical base for researchers and small companies with low
  integration cost
