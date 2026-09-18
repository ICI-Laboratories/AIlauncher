# Guía de Integración y Adaptación: AIlauncher (lmserver) para SaraPad

> **Destinatario**: Desarrollador responsable de `AIlauncher` / `lmServer`.  
> **Origen**: Integración de `sarapad-backend` (`assessment-service`) como cliente de inferencia LLM centralizada en `cite-server`.  
> **Fecha**: Septiembre 2026.

---

## 1. Contexto y Arquitectura

**SaraPad** es el entorno de práctica y evaluación guiada de programación de la suite ICI-Laboratories. Anteriormente, consumía inferencia a través de procesos aislados o locales de Ollama/llamacpp.

Se ha adaptado `sarapad-backend` para conectarse a **`AIlauncher`** (`lmserver`) como gateway único de inferencia sobre GPUs compartidas en `cite-server` (`http://llm-gateway:8000/v1` en red `llm-apps` o `127.0.0.1:8009/v1` en host).

El principio de diseño es: **las aplicaciones cliente no deben recortar sus payloads ni degradar sus pipelines educativas; es el gateway de AIlauncher quien debe gobernar, adaptar y normalizar el tráfico de inferencia.**

---

## 2. Flujos y Requerimientos de Payload de SaraPad

SaraPad ejecuta 4 pipelines principales sobre `/v1/chat/completions`:

| Pipeline | Propósito | `max_tokens` requerido | `response_format` | Tolerancia a latencia |
| :--- | :--- | :--- | :--- | :--- |
| **`sarapad_prepare_problem`** | Preparación y refinamiento de problemas pedagógicos (enunciado, solución, casos de prueba unitarios, hints). | **2200 – 4096** | `{"type": "json_object"}` | Normal (10s – 30s) |
| **`sarapad_generate_problem`**| Generación interactiva de problemas según nivel y tema. | **1400 – 2000** | `{"type": "json_object"}` | Media (5s – 15s) |
| **`sarapad_review_code`** | Revisión de código de estudiantes con feedback formativo línea por línea. | **700 – 1000** | `{"type": "json_object"}` | **Crítica (< 2s - 4s)** |
| **`sarapad_evaluate_step`** | Evaluación paso a paso del código del estudiante y pistas incrementales. | **700 – 1000** | `{"type": "json_object"}` | **Crítica (< 2s - 3s)** |

### Parámetros típicos enviados por SaraPad:
- `model`: `"qwen-local"` (o el modelo principal activo en el gateway).
- `messages`: Arreglo estándar de mensajes `system` (instrucciones de formateo JSON estricto) y `user` (código, enunciados, consignas).
- `temperature`: `0.2` a `0.5` para garantizar determinismo y sintaxis JSON válida.
- `response_format`: `{"type": "json_object"}`.
- `Authorization`: `Bearer <API_KEY>` (clave de la aplicación `sarapad`).

---

## 3. Puntos de Fricción Identificados y Métodos Propuestos para AIlauncher

Durante las pruebas de integración en `cite-server`, se identificaron comportamientos en `AIlauncher/lmserv/server/shared_api.py` que requieren atención para que el servicio opere de forma robusta con SaraPad y futuros clientes.

---

### Propuesta 1: Clamping Transparente de Tokens vs. Error HTTP 422

#### Situación Actual:
En `lmserv/server/shared_api.py` (líneas 279-281):
```python
limit = payload.max_tokens or payload.max_completion_tokens or cfg.max_output_tokens
if limit > cfg.max_output_tokens:
    raise HTTPException(422, f"Output budget exceeds {cfg.max_output_tokens} tokens")
```
Actualmente `MAX_OUTPUT_TOKENS = 2048` por defecto. Si `sarapad_prepare_problem` solicita `2200` tokens para generar un problema con tests y hints completos, **AIlauncher rechaza la petición con HTTP 422**.

#### Métodos Propuestos:

- **Método 1.A (Recomendado - Clamping Suave)**:
  En lugar de abortar con 422, recortar transparentemente al máximo permitido por la configuración:
  ```python
  limit = min(payload.max_tokens or cfg.max_output_tokens, cfg.max_output_tokens)
  ```
  Opcionalmente añadir un header de respuesta HTTP `X-Tokens-Clamped: true` para visibilidad en métricas.

- **Método 1.B (Recomendado para Producción en `cite-server`)**:
  Aumentar el presupuesto en `/etc/ailauncher/gateway.env` o en `compose.shared.yml`:
  ```env
  MAX_OUTPUT_TOKENS=4096
  ```
  *Justificación técnica*: El proceso `llama-server` subyacente corre con un context window de `32,768` tokens y slots de `8,192` tokens en las GPUs RTX A4000. Permitir hasta 4096 tokens de salida no satura la memoria VRAM y cubre las necesidades de generación de código estructurado con tests.

- **Método 1.C (Presupuesto por Aplicación)**:
  Permitir configurar presupuestos máximos diferenciados por cliente en `app-keys.json` o settings (ej. `sarapad` con 4096 tokens, `smartdoc` con 2048 tokens).

---

### Propuesta 2: Fallback Tolerante de Alias de Modelo vs. Error HTTP 404

#### Situación Actual:
En `lmserv/server/shared_api.py` (líneas 275-276):
```python
alias = payload.model or cfg.aliases[0]
if alias not in cfg.aliases:
    raise HTTPException(404, "Unknown model alias")
```
Si una biblioteca cliente o pipeline envía `default`, `qwen3:8b`, `qwen`, `gpt-4o-mini` o cualquier alias no explícito, el gateway aborta con HTTP 404.

#### Métodos Propuestos:

- **Método 2.A (Fallback con Warning al Modelo Activo)**:
  Si el alias solicitado no se encuentra en `cfg.aliases`, usar automáticamente el modelo principal (`cfg.aliases[0]`), registrando la advertencia en el log estructurado:
  ```python
  if alias not in cfg.aliases:
      logger.warning("Unknown model alias '%s' requested by app '%s'; defaulting to '%s'", alias, app_id, cfg.aliases[0])
      alias = cfg.aliases[0]
  ```
- **Método 2.B (Registro de Alias de Compatibilidad)**:
  Incluir en `MODEL_ALIASES` en `gateway.env`:
  ```env
  MODEL_ALIASES=qwen-local,sara-main,local-model,sarapad-default,default
  ```

---

### Propuesta 3: Admisión Basada en Prioridad (`X-Priority` / Interactive vs. Batch)

#### Situación Actual:
`AdmissionController` (`lmserv/server/admission.py`) diferencia entre cargas `text` y `vision`, con un límite de concurrencia global (`MAX_INFLIGHT=4`) y por aplicación (`PER_APP_INFLIGHT=2`).

#### Necesidad de SaraPad:
- Una solicitud de **`sarapad_review_code`** o **`sarapad_evaluate_step`** tiene al estudiante esperando activamente frente al editor. Si se encola detrás de una tarea batch pesada, la experiencia se degrada.
- En cambio, una solicitud de **`sarapad_prepare_problem`** es una tarea de background/docente que puede esperar 20-40 segundos en cola sin inconveniente.

#### Método Propuesto:
Soportar un header opcional:
```http
X-Priority: interactive
```
(o `X-Priority: high` vs `X-Priority: batch`).
En `lmserv/server/admission.py`, asignar tickets de prioridad a la cola de entrada para que las solicitudes interactivas adelanten a las solicitudes de lote cuando haya contención.

---

### Propuesta 4: Endpoint de Salud Ligero (`/healthz` o `/readyz`)

#### Situación Actual:
- `GET /health` responde `{"status": "ok"}` sin autenticación, pero solo verifica que el proceso Uvicorn de AIlauncher esté vivo, no si el motor backend `llama-server` está listo.
- `GET /ready` verifica el backend (`llama-server`), pero requiere autenticación (`Authorization: Bearer <APP_KEY>`).

#### Método Propuesto:
Mantener `/ready` autenticado para clientes, pero proveer un endpoint ligero o flag público (ej. `GET /readyz` o respuesta enriquecida en `/health`) que permita a los healthchecks de Docker o balanceadores monitorear la salud del motor LLM sin necesidad de inyectar secretos de aplicación en los checks de orquestación.

---

### Propuesta 5: Incorporación Oficial de `sarapad` en `create-app-keys.py`

#### Cambio Requerido en AIlauncher:
En `AIlauncher/deploy/create-app-keys.py`, añadir `'sarapad'` a la tupla `apps`:
```python
apps = (
    'admin', 'sara', 'skilldex', 'alumni', 'examgen',
    'slidercreator', 'smartdoc', 'enterprisechat', 'guardai',
    'agentagenda', 'sarapad'
)
```

> [!NOTE]
> En el servidor de producción `cite-server`, la clave para `sarapad` ya fue aprovisionada de forma segura en:
> - Clave central: `/etc/ailauncher/app-keys.json` (UID 10001:10001, permisos 0400).
> - Archivo del cliente: `/home/cite/local-ai/clients/sarapad.env` (permisos 0600).
> 
> Al correr `create-app-keys.py` en el futuro, el script preserva las claves existentes (`keys.setdefault(...)`), por lo que la clave de `sarapad` no se sobreescribirá.

---

## 4. Ejemplos de Invocación de SaraPad hacia AIlauncher

### Verificación de Estado (`/ready`):
```bash
curl -s -H "Authorization: Bearer <SARAPAD_API_KEY>" \
  http://llm-gateway:8000/ready
```
**Respuesta esperada:**
```json
{"status": "ready", "model": "qwen-local", "context_tokens": 8192}
```

### Consulta de Modelos (`/v1/models`):
```bash
curl -s -H "Authorization: Bearer <SARAPAD_API_KEY>" \
  http://llm-gateway:8000/v1/models
```
**Respuesta esperada:**
```json
{
  "object": "list",
  "data": [
    {"id": "qwen-local", "object": "model", "owned_by": "local", "created": 0},
    {"id": "sara-main", "object": "model", "owned_by": "local", "created": 0},
    {"id": "local-model", "object": "model", "owned_by": "local", "created": 0}
  ]
}
```

### Inferencia Estructurada JSON (`/v1/chat/completions`):
```bash
curl -s -X POST http://llm-gateway:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <SARAPAD_API_KEY>" \
  -d '{
    "model": "qwen-local",
    "messages": [
      {"role": "system", "content": "Eres un tutor de programación. Responde estrictamente en JSON."},
      {"role": "user", "content": "Genera un ejercicio simple de arreglos en Python."}
    ],
    "temperature": 0.3,
    "max_tokens": 2200,
    "response_format": {"type": "json_object"}
  }'
```

---

## 5. Resumen de Acciones Sugeridas para el Dev de AIlauncher

1. **Corto plazo**:
   - Ajustar `MAX_OUTPUT_TOKENS=4096` en `/etc/ailauncher/gateway.env` en `cite-server`.
   - Modificar la validación de `max_tokens` en `shared_api.py` para recortar con `min(...)` en lugar de fallar con `HTTP 422`.
   - Añadir `'sarapad'` a la lista `apps` en `deploy/create-app-keys.py`.
2. **Mediano plazo**:
   - Implementar fallback tolerante de alias a `cfg.aliases[0]` en lugar de error 404.
   - Evaluar soporte de prioridad `X-Priority: interactive` en `AdmissionController`.
