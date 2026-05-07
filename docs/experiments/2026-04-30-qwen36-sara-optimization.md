# qwen3.6 SARA optimization - 2026-04-30

## Objetivo

Optimizar el modelo base usado por la aplicacion en produccion sin migrar de
backend ni detener SARA. El modelo base era `qwen3.6:35b` servido por Ollama a
traves de LMLauncher.

## Cambio aplicado

Se creo un modelo derivado en Ollama:

```text
qwen3.6-sara:opt
```

Modelfile efectivo:

```text
FROM qwen3.6:35b
PARAMETER num_ctx 4096
PARAMETER num_gpu 24
PARAMETER temperature 0
PARAMETER min_p 0
PARAMETER top_p 0.95
PARAMETER top_k 20
PARAMETER repeat_penalty 1
PARAMETER presence_penalty 1.5
```

LMLauncher quedo apuntando `sara-main` a:

```text
qwen3.6-sara:opt
```

Catalogo desplegado:

```json
{
  "target": "qwen3.6-sara:opt",
  "settings": {
    "think": false,
    "keep_alive": "30m",
    "options": {
      "num_ctx": 4096,
      "num_gpu": 24
    }
  }
}
```

Backup remoto antes del cambio:

```text
/srv/ai-data/ailauncher/archive/config-20260430T092250Z
```

## Resultados previos

Pruebas directas en Ollama:

| Perfil | Capas GPU | Procesador | Wall caliente | Prompt t/s | Generacion t/s |
|---|---:|---|---:|---:|---:|
| `qwen3.6:35b`, `num_ctx=4096`, auto GPU | 9/41 | 78%/22% CPU/GPU | 7.05 s | 4.09 | 2.78 |
| `qwen3.6:35b`, `num_ctx=4096`, `num_gpu=20` | 20/41 | 54%/46% CPU/GPU | 3.97 s | 8.35 | 2.28 |
| `qwen3.6:35b`, `num_ctx=4096`, `num_gpu=24` | 24/41 | 45%/55% CPU/GPU | 3.63 s | 8.25 | 2.36 |

Se eligio `num_gpu=24` porque cabe en una sola RTX A4000 durante la deteccion
actual de Ollama y aumenta el offload sin forzar el perfil riesgoso
`num_gpu=999`.

## Validacion por gateway

Primera peticion por LMLauncher despues del cambio:

```text
wall_s=66.80
content=OK
usage={"prompt_tokens":16,"completion_tokens":2,"total_tokens":18}
```

La primera peticion incluye carga del modelo.

Segunda peticion caliente:

```text
wall_s=4.35
content=OK
usage={"prompt_tokens":16,"completion_tokens":2,"total_tokens":18}
```

Prueba con `response_format={"type":"json_object"}`:

```text
structured_wall_s=6.77
content={"estado":"ok"}
usage={"prompt_tokens":19,"completion_tokens":6,"total_tokens":25}
```

Estado de Ollama despues de la prueba:

```text
qwen3.6-sara:opt
processor: 45%/55% CPU/GPU
context: 4096
keep_alive: 29 minutes
```

Logs de carga:

```text
offloaded 24/41 layers to GPU
model weights CUDA0: 12.2 GiB
model weights CPU: 10.1 GiB
kv cache CUDA0: 990.2 MiB
kv cache CPU: 660.1 MiB
```

## Estado de produccion

Despues del cambio:

```text
system=running
ailauncher=active
ollama=active
docker=active
sara-backend=active
sara-backend-tunnel=active
systemctl --failed: 0
```

No se reinicio Ollama, Docker ni SARA. Solo se reinicio `ailauncher` para
recargar el catalogo y el runtime actualizado.

## Decision

El perfil queda como optimizacion de produccion para el modelo base actual.
No se recomienda subir a `num_gpu=999` hasta estabilizar la deteccion multi-GPU
de Ollama, porque puede fallar si el runner detecta una sola RTX A4000.

## Actualizacion 2026-05-07

La validacion final para el paper uso el mismo modelo derivado
`qwen3.6-sara:opt`, pero el catalogo productivo envio por solicitud
`num_gpu=41`, `num_batch=512`, `num_thread=24` y `keep_alive=24h`. Ese perfil
reemplaza al perfil conservador `num_gpu=24` como referencia productiva actual.
Ver: [2026-05-07: validacion final para paper](2026-05-07-paper-validation.md).
