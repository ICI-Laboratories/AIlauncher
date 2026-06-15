# Server Deployment Notes

## Estado actual validado (2026-05-13 UTC)

El estado productivo para demo ya no usa el perfil historico `qwen3:30b`.
El despliegue activo usa:

- Servidor: `fimenibblegpu`
- OS/kernel: Ubuntu 24.04.4 LTS, `6.8.0-111-generic`
- GPU: 2 x NVIDIA RTX A4000, 16376 MiB cada una
- Driver NVIDIA: `595.58.03`
- Gateway: `AIlauncher` en `0.0.0.0:8009`
- Runtime: `Ollama` local en `127.0.0.1:11434`
- Modelo default: `sara-main`
- Target Ollama: `qwen3.6-sara:opt`
- Catalogo: `/opt/ailauncher/app/deploy/models.server.json`
- Backend activo: `ollama`
- `keep_alive`: `5m`
- Opciones: `num_ctx=4096`, `num_gpu=41`, `num_batch=512`, `num_thread=24`

Clientes activos:

- SARA: `DOCKER_LLM_URL=http://host.docker.internal:8009/v1`
- SkillDex: `AILAUNCHER_BASE_URL=http://host.docker.internal:8009`

Tunnels publicos:

- SkillDex API: `https://skilldexapi.ici-labs.com`
- SARA API: `https://sarabackendapi.ici-labs.com`

Runbook completo:

```text
docs/operations/2026-05-12-skilldex-sara-demo-runbook.md
```

Nota: el perfil anterior de `keep_alive=24h` se cambio a `5m` para proteger
memoria si el servidor vuelve a caer a CPU por un problema de driver GPU.

## Objetivo

Este perfil deja `AIlauncher` listo en un servidor Linux como gateway
OpenAI-compatible para `SARA`, usando `Ollama` como runtime local.

## Perfil recomendado

- Puerto HTTP del gateway: `8009`
- URL base para clientes: `http://HOST:8009/v1`
- Runtime local: `http://127.0.0.1:11434`
- Modelo principal: `qwen3:30b`
- Log de investigacion: JSONL en `requests.jsonl`
- `think=false` para priorizar salida util sobre razonamiento oculto

## Flujo

1. Instalar `Ollama`.
2. Hacer `pull` de `qwen3:30b`.
3. Instalar `AIlauncher` en un `venv`.
4. Crear un `EnvironmentFile` fuera del repo con `API_KEY`.
5. Ejecutar `lmserv serve --catalog deploy/models.server.json --port 8009`.
6. Guardar auditoria en un JSONL para analisis posterior del paper.

## Variables minimas

```bash
API_KEY=<secret>
REQUEST_LOG_PATH=/var/log/ailauncher/requests.jsonl
REQUEST_LOG_INCLUDE_CONTENT=1
REQUEST_LOG_MAX_CHARS=12000
```

## Integracion con SARA

Para Docker Compose en `SARA`:

- `DOCKER_LLM_URL=http://host.docker.internal:8009/v1`
- `DEFAULT_LLM_MODEL=sara-main`
- `TAS_LLM_API_KEY=<mismo API_KEY del launcher>`
- `AS_LLM_API_KEY=<mismo API_KEY del launcher>`

Con eso, TAS y Assessment siguen hablando con un endpoint tipo OpenAI sin
depender directamente de la forma exacta del API de `Ollama`.

## Nota sobre modelos alternos

`gemma4:26b` tambien es una opcion valida en Ollama, pero en este servidor
la dejamos fuera del perfil base para no agotar el disco. Si despues amplias
el almacenamiento, se puede agregar como ruta secundaria en el catalogo.
