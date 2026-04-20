# Server Deployment Notes

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
