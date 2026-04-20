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
- Paper en borrador: [paper/CIREDII2026_LMLauncher_Draft.md](paper/CIREDII2026_LMLauncher_Draft.md)
- Catalogo de ejemplo: [models.example.json](models.example.json)
