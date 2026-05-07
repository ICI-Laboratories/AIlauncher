# LMLauncher

LMLauncher esta evolucionando de un servidor local acoplado a `llama.cpp`
hacia un gateway para aplicaciones basadas en LLM. La meta es que
investigadores, laboratorios y pequenas empresas puedan apuntar sus
herramientas a una sola URL y dejar que el launcher resuelva que motor y que
modelo usar.

## Que resuelve

- una capa de compatibilidad tipo OpenAI para herramientas existentes
- seleccion de backend entre `llama.cpp` y `Ollama`
- catalogo de modelos con alias y capacidades
- fallback automatico cuando una peticion requiere `structured output`
- una base mas limpia para escalar horizontalmente despues

## Arquitectura base

```text
Client App
   |
   v
/v1/chat/completions
   |
   v
Gateway API
   |
   +--> Model Catalog
   |
   +--> Capability Resolver
   |
   +--> llama.cpp Runtime
   |
   +--> Ollama Runtime
```

## Modo simple

### `llama.cpp`

```bash
lmserv serve --backend llama_cpp --model models/main.gguf
```

### `Ollama`

```bash
lmserv serve --backend ollama --model llama3.1:8b --ollama-base-url http://localhost:11434
```

## Modo catalogo

Usa un archivo JSON para definir varias rutas de inferencia:

```bash
lmserv serve --catalog models.example.json
```

Ejemplo de comportamiento:

- `research-main` atiende la conversacion general
- `research-structured` se usa como fallback cuando la solicitud pide
  `response_format` y el modelo principal no soporta salida estructurada

## Observabilidad para el paper

El gateway puede guardar cada solicitud en un archivo JSONL para estudiar:

- prompts y respuestas truncadas
- seleccion de modelo y razon de ruteo
- uso de tokens reportado por el backend
- tamanos de contexto y herramientas pedidas

Ejemplo:

```bash
lmserv serve \
  --catalog deploy/models.server.json \
  --port 8009 \
  --request-log-path logs/requests.jsonl \
  --request-log-include-content \
  --request-log-max-chars 12000
```

Variables equivalentes:

- `REQUEST_LOG_PATH`
- `REQUEST_LOG_INCLUDE_CONTENT=1`
- `REQUEST_LOG_MAX_CHARS=12000`

El archivo queda en formato JSON Lines para poder procesarlo despues con
Python, DuckDB o notebooks.

## Perfil recomendado para SARA

El repositorio incluye un catalogo pensado para servidor con Ollama:

```bash
lmserv serve --catalog deploy/models.server.json --port 8009
```

En el perfil ajustado para este servidor, `sara-main` apunta a
`qwen3.6-sara:opt`, un derivado de `qwen3.6:35b` pensado para SARA. El catalogo
fija `think=false`, `num_ctx=4096`, `num_gpu=41`, `num_batch=512`,
`num_thread=24` y `keep_alive=24h` para mantener el modelo caliente y evitar
que el presupuesto de tokens se consuma en razonamiento oculto antes de emitir
el JSON que espera SARA.

La validacion del 2026-05-07 confirmo que esta ruta responde `/health`,
`/v1/models`, `json_object`, `json_schema`, generacion larga y concurrencia
ligera sin dejar servicios fallidos. Si mas adelante se agrega una segunda
ruta experimental, conviene mantenerla con baja prioridad hasta medirla con
prompts reales de SARA.

## Integracion desde una app existente

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="changeme",
)

response = client.chat.completions.create(
    model="research-main",
    messages=[
        {"role": "user", "content": "Devuelve un resumen en formato estructurado"}
    ],
)

print(response.choices[0].message.content)
```

## Endpoints principales

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /chat` como endpoint legado

## Estado actual

Esta version ya introduce la base del gateway, pero aun faltan varias piezas
para cumplir la vision completa del paper:

- streaming token a token por backend
- balanceo distribuido y scheduler multi-nodo
- conectores formales para herramientas externas
- observabilidad y metricas de capacidad
- evaluacion experimental de rendimiento

## Documentos del proyecto

- Arquitectura: [docs/lmlauncher-architecture.md](docs/lmlauncher-architecture.md)
- Despliegue en servidor: [docs/server-deployment.md](docs/server-deployment.md)
- Flujo de actualizacion remota: [docs/update-workflow.md](docs/update-workflow.md)
- Decision de optimizacion GPU: [docs/optimization-decision.md](docs/optimization-decision.md)
- Experimento de build CUDA: [docs/gpu-optimized-build-experiment.md](docs/gpu-optimized-build-experiment.md)
- Validacion final para paper: [docs/experiments/2026-05-07-paper-validation.md](docs/experiments/2026-05-07-paper-validation.md)
- Catalogo de ejemplo: [models.example.json](models.example.json)
- Catalogo recomendado para SARA: [deploy/models.server.json](deploy/models.server.json)
