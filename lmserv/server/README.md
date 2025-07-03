# `lmserv/server` – capa HTTP + workers

Este paquete agrupa **todo** lo necesario para exponer la API
REST/streaming y para orquestar los procesos `llama-cli`.

```

server/
├── **init**.py      # logger + re-exports
├── api.py           # FastAPI + rutas
├── pool.py          # WorkerPool (spawn / acquire / release / shutdown)
├── security.py      # API-Key, CORS, rate-limit
└── workers/         # familia de workers (llama, cpp\_bridge…)

````

## Quick start

```bash
# arrancar API (usa Config por defecto)
python -m lmserv.cli serve --model-path models/gemma.gguf --workers 2
# probar salud
curl -H "X-API-Key: changeme" http://localhost:8000/health
# chat streaming
curl -N -X POST -H "X-API-Key: changeme" \
     -H "Content-Type: application/json" \
     -d '{"prompt":"Hola ¿quién eres?","max_tokens":64}' \
     http://localhost:8000/chat
````

## Estructura

| Archivo       | Rol                             | \~líneas |
| ------------- | ------------------------------- | -------- |
| `api.py`      | FastAPI App, models, endpoints  | 120      |
| `pool.py`     | Orquestador de workers          | 140      |
| `security.py` | Auth + CORS + rate-limit (stub) | 90       |
| `workers/`    | Implementaciones de *workers*   | ≤300 c/u |

## Cambios recientes

| Fecha        | Autor       | Descripción                                             |
| ------------ | ----------- | ------------------------------------------------------- |
| 2024-06-\*\* | @tu-usuario | **refactor:** separamos `api`, `pool`, `security` (#12) |

## Pendiente

* [ ] Implementar rate-limit real (Redis).
* [ ] Endpoint `/metrics` (Prometheus).
* [ ] Tests `pytest-asyncio` de **/chat** con pool=3.



