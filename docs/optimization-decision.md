# Optimization Decision Notes

## Estado corto

No conviene migrar produccion todavia, pero si conviene abrir una ruta
experimental `llama.cpp` para pruebas A/B.

El hallazgo principal es que el servidor no esta limitado por la compilacion
solamente, sino por cuanto del modelo logra quedar en GPU. Cuando `qwen3:30b`
corre con pocas capas GPU, la generacion es muy lenta. Cuando el mismo modelo
queda con offload alto en las RTX A4000, el rendimiento sube de forma drastica.

## Resultados medidos

Modelo usado para benchmark:

```text
qwen3:30b Q4_K_M
```

Binario experimental:

```text
llama.cpp CUDA sm_86
```

Resultados `llama-bench`:

| Configuracion | Prompt t/s | Generacion t/s |
|---|---:|---:|
| `llama.cpp`, 4 capas GPU | 13.18 | 0.67 |
| `llama.cpp`, offload alto (`-ngl 999`) | 866.35 | 93.31 |

Resultado Ollama conservador:

| Configuracion | Prompt t/s | Generacion t/s | Notas |
|---|---:|---:|---|
| `qwen3:30b`, `num_ctx=4096`, sin forzar `num_gpu` | 5.02 | 1.27 | 68%/32% CPU/GPU |

Resultado para el modelo base actual de la app:

| Configuracion | Prompt t/s | Generacion t/s | Notas |
|---|---:|---:|---|
| `qwen3.6:35b`, `num_ctx=4096`, auto GPU | 4.09 | 2.78 | 9/41 capas GPU, 78%/22% CPU/GPU |
| `qwen3.6:35b`, `num_ctx=4096`, `num_gpu=20` | 8.35 | 2.28 | 20/41 capas GPU, 54%/46% CPU/GPU |
| `qwen3.6:35b`, `num_ctx=4096`, `num_gpu=24` | 8.25 | 2.36 | 24/41 capas GPU, 45%/55% CPU/GPU |

Validacion productiva posterior del gateway:

| Configuracion | Prueba | Latencia media | Generacion |
|---|---|---:|---:|
| `qwen3.6-sara:opt`, `num_ctx=4096`, `num_gpu=41`, `keep_alive=24h` | `json_schema`, n=3 | 1.597 s | 13.21 tokens/s |
| `qwen3.6-sara:opt`, `num_ctx=4096`, `num_gpu=41`, `keep_alive=24h` | `controlled_256`, n=3 | 6.826 s | 37.53 tokens/s |
| `qwen3.6-sara:opt`, `num_ctx=4096`, `num_gpu=41`, `keep_alive=24h` | `assessment_like_512`, n=2 | 12.718 s | 40.26 tokens/s |

Se creo un modelo derivado en Ollama:

```text
qwen3.6-sara:opt
```

Parametros del modelo:

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

Nota: el Modelfile conserva un perfil conservador, pero el catalogo productivo
validado envia `num_gpu=41` por solicitud mediante `settings.options`.

El perfil inicial fue aplicado a produccion el 2026-04-30. El gateway
`sara-main` ahora apunta a `qwen3.6-sara:opt`. La configuracion validada el
2026-05-07 usa `keep_alive=24h`, `num_gpu=41`, `num_batch=512` y
`num_thread=24`.

Validacion por LMLauncher:

```text
primera llamada: 66.80 s, incluye carga del modelo
segunda llamada caliente: 4.35 s
structured output caliente: 6.77 s
```

Validacion final para el paper:

```text
artefactos: /srv/ai-data/ailauncher/experiments/paper-validation-final-20260507T064642Z
health: 200
/v1/models con API key: 200
json_schema: 3/3 JSON valido, media 1.597 s
json_object: 3/3 JSON valido, media 1.739 s
controlled_256: 3/3 HTTP 200, media 6.826 s
assessment_like_512: 2/2 HTTP 200, media 12.718 s
concurrent_2: 2/2 HTTP 200, pared total 4.844 s
servicios despues: running, 0 unidades fallidas
```

Backup remoto del cambio:

```text
/srv/ai-data/ailauncher/archive/config-20260430T092250Z
```

Observacion Ollama de alto offload:

- Una corrida con `num_gpu=999` logro 49/49 capas en GPU y una segunda peticion
  caliente de aproximadamente 0.79 s.
- Otra corrida con `num_gpu=999` detecto solo una GPU y fallo por memoria.

## Recomendacion

Mantener produccion en Ollama por ahora, usando el modelo derivado
`qwen3.6-sara:opt` para la ruta base de SARA y el perfil validado el
2026-05-07.

No desplegar todavia:

```json
{"num_gpu": 999}
```

Motivo: puede ser muy rapido, pero la deteccion multi-GPU de Ollama fue
inestable durante las pruebas. Si detecta una sola RTX A4000, intenta cargar
demasiado en una tarjeta y falla.

Siguiente paso recomendado:

1. Levantar `llama-server` experimental en un puerto alterno, por ejemplo `8010`.
2. Exponerlo en LMLauncher como una ruta adicional deshabilitada o de baja
   prioridad.
3. Ejecutar pruebas A/B con prompts reales de SARA.
4. Medir latencia total, tokens/s, errores JSON, uso VRAM y estabilidad.
5. Migrar solo si la ruta `llama.cpp` mantiene calidad y confiabilidad.

## Seguridad operacional

Durante los experimentos no se reiniciaron servicios de produccion. El estado
final verificado fue:

```text
system=running
ailauncher=active
ollama=active
docker=active
sara-backend=active
sara-backend-tunnel=active
systemctl --failed: 0
ollama ps: vacio
GPU memory: 0 MiB usada
```

`ailauncher` siguio respondiendo `/health` y `/v1/models`.

Ejecucion detallada:

- [2026-04-30: optimizacion de qwen3.6 para SARA](experiments/2026-04-30-qwen36-sara-optimization.md)
