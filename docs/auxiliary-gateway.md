# Fase 2: gateway de chat, OCR y embeddings

> Este documento describe la fase de incorporación del contrato. Para los modelos
> y límites finalmente instalados en cite-server, ver el
> [runbook de auxiliares activos](../deploy/auxiliary/README.md).

El servicio `lmserv.server.shared_api` concentra las llamadas de las apps y las
envía a procesos persistentes de llama.cpp. Cada proceso conserva su propio
modelo y límites. Esta fase agrega enrutamiento y contratos; no instala modelos,
no usa GPU, no inicia servidores de inferencia ni cambia las aplicaciones.

```text
Apps -> AIlauncher (Bearer por aplicación)
          ├─ /v1/chat/completions + sara-main -> llama.cpp de chat actual
          ├─ /v1/chat/completions + ocr       -> llama.cpp OCR, opt-in
          └─ /v1/embeddings + bge-m3          -> llama.cpp embeddings, opt-in
```

## Compatibilidad y selección de modelo

`MODEL_BACKEND_URL`, `MODEL_BACKEND_MODEL`, `MODEL_ALIASES` y los límites actuales
siguen definiendo el chat. Su URL backend debe terminar en `/v1`. No reemplazar
los límites validados de producción por los valores de ejemplo.

El primer alias de chat es el predeterminado si se omite `model`. Un alias
desconocido o desactivado devuelve **404** sin contactar ningún motor; un modelo
de embeddings usado en chat, o viceversa, devuelve **409**. No se cambia a otro
motor ante errores, colas llenas o capacidades ausentes. Esto elimina el antiguo
fallback de aliases desconocidos al modelo principal.

Los aliases deben ser únicos entre rutas. Las rutas requieren URLs backend
distintas: dos colas independientes no deben representar el mismo proceso de
inferencia. La URL es configuración administrativa, no un campo del request.
No contiene credenciales, query ni fragmento. `deploy/models.shared.json` sigue
siendo inventario documental; no configura las rutas. Los catálogos heredados
de Ollama tampoco intervienen en este gateway.

## Estado por defecto

`OCR_ENABLED=false` y `EMBEDDINGS_ENABLED=false`. Sus URLs pueden permanecer
vacías: no habrá comprobaciones, conexiones ni descarga de modelos auxiliares.
`/v1/models` publica solamente los aliases habilitados, con campos adicionales
`category` (`chat`, `ocr`, `embeddings`) y `operation` (`chat`, `embeddings`).
Habilitado significa configurado, no que el backend esté disponible.

Conservar en las apps `SARA_OCR_MODEL=` y `SARA_EMBEDDING_MODEL=` hasta completar
la fase de modelos y sus pruebas reales. El chat y el OCR CPU de las apps
siguen funcionando como en la fase anterior.

## Configuración futura de auxiliares

Las variables se documentan en `deploy/shared.example.env` y se pasan al
contenedor en `deploy/compose.shared.yml`. No se añadieron servicios GPU ni
puertos de host para los auxiliares. Estos nombres son ejemplos de servicios
futuros en la red privada `llm-backend`, no servidores creados por esta entrega:

```dotenv
OCR_ENABLED=false
OCR_BACKEND_URL=http://ocr-inference:8080/v1
OCR_BACKEND_MODEL=glm-ocr
OCR_MODEL_ALIASES=ocr

EMBEDDINGS_ENABLED=false
EMBEDDINGS_BACKEND_URL=http://embeddings-inference:8080/v1
EMBEDDINGS_BACKEND_MODEL=bge-m3
EMBEDDINGS_MODEL_ALIASES=bge-m3
```

Después de validar cada modelo, cambiar su flag a `true` requiere reiniciar
solamente el gateway en un despliegue controlado. No hay recarga en caliente.
Las claves permanecen en `APP_KEYS_FILE`; todas las rutas requieren la clave de
la aplicación. Las claves del gateway no se reenvían a llama.cpp. La red privada
protege el acceso a los backends; no exponerlos directamente a las apps.

## Límites y colas

| Límite | Chat | OCR | Embeddings |
| --- | --- | --- | --- |
| Activas por backend, ejemplo | 4 (`MAX_INFLIGHT`) | 1 | 1 |
| Activas por app, ejemplo | 2 | 1 | 1 |
| Cola máxima | 32 | 8 | 8 |
| Espera máxima en cola | 60 s | 30 s | 30 s |
| Solicitud al backend | 300 s | 120 s | 120 s |
| Cuerpo HTTP entrante | 16 MiB | 16 MiB | 1 MiB |
| Salida máxima de chat | 2048 tokens | 4096 tokens | Vector de 1024 valores |

Cada columna tiene su propio controlador de admisión y pool de conexiones.
La cancelación devuelve el slot a esa ruta, incluida la cancelación de un stream.
Un servicio saturado no consume slots de otro; sí puede competir por la misma
GPU en la fase de modelos. Un solo proceso Uvicorn y una sola réplica son
obligatorios: multiplicar workers/replicas multiplica los límites.

Cola llena devuelve **429**, espera agotada **503**, timeout del backend **504**;
se conserva `Retry-After` cuando corresponde. Las respuestas de error del backend
se sustituyen por mensajes genéricos, sin copiar documentos ni imágenes. Los
logs contienen identificadores, ruta, tiempos y conteos numéricos de tokens.

Los topes de salida de chat se aplican por ruta; solicitudes mayores reciben
`X-Tokens-Clamped: true`. `MAX_CONTEXT_TOKENS` describe la configuración esperada;
el gateway no ejecuta el tokenizer de cada modelo. Los límites de texto usan
caracteres, no tokens. El motor sigue validando su contexto real. Estos controles
no crean una cuota de VRAM ni garantizan el margen de 5 GiB de la 3090.

## Contratos de auxiliares

**OCR** conserva `/v1/chat/completions`, autenticación y respuesta de chat.
Requiere exactamente una imagen PNG/JPEG inline en `image_url`, hasta 8 MiB y
2048 píxeles por lado. Valida encabezados/dimensiones; la decodificación completa
es del motor. No acepta URLs remotas, audio, video ni imágenes adicionales.
El texto de cada bloque se limita a 8192 caracteres y a 65536 en total. Los
prompts preparados por las apps se transmiten al modelo sin reemplazarlos.

**Embeddings** recibe texto o una lista de textos:

```json
{"model":"bge-m3","input":["Texto del documento","Consulta"],"encoding_format":"float"}
```

Máximo 16 textos por llamada, 8192 caracteres por texto y 65536 en total;
no acepta entradas vacías, arrays de IDs de tokens ni formato base64. `dimensions`
opcional debe coincidir con `EMBEDDINGS_DIMENSIONS`; es una comprobación, no una
proyección de vectores. La respuesta es OpenAI-compatible: `object: "list"`,
`data` con índices ordenados, `embedding` de 1024 números finitos y `model` con
el alias público. Se rechazan respuestas incompletas, índices repetidos,
vectores cero y dimensiones distintas. Los cuerpos de respuesta tienen tamaño
acotado; un backend que devuelva otra forma produce **502**.

## Salud y métricas

- `/health`: vida del proceso, sin autenticación. No certifica un motor.
- `/ready`: con clave, comprueba solo el chat predeterminado.
- `/ready?model=ocr` o `?model=bge-m3`: comprueba el backend del alias habilitado;
  un auxiliar caído no vuelve indisponible la comprobación del chat.
- `/v1/models`: catálogo de aliases habilitados, con clave; no expone URLs internas.
- `/metrics`: clave `admin`; conserva los campos superiores del chat para
  compatibilidad y añade `routes.chat`, `routes.ocr`, `routes.embeddings` según
  lo habilitado. Un cliente normal no puede leer métricas administrativas.

Una comprobación `/ready` confirma que `/models` del backend anuncia el modelo
configurado. La prueba real de inferencia y el benchmark siguen siendo necesarios.

## Validación y despliegue posterior

```sh
python -m pytest -q
docker compose --env-file deploy/shared.example.env -f deploy/compose.shared.yml config --quiet
```

La suite simula backends HTTP y prueba enrutamiento, ausencia de fallback,
autenticación, datos multimodales, streaming, desconexiones, colas por servicio,
límites y vectores. No descarga modelos ni mide GPU. `deploy/validate-live.py` es
una prueba opt-in de producción con inferencia: no se ejecutó en esta fase.

Antes de desplegar, revisar que las apps usan aliases declarados: los errores
de nombre que antes se ocultaban ahora son 404. Conservar configuración y versión
anterior del gateway para reversión, drenar solicitudes activas y desplegar solo
el servicio gateway con auxiliares desactivados. Verificar chat, `/ready`,
catálogo, un alias inexistente y `/metrics`. No reiniciar el llama-server principal.

La última fase será instalar y medir los modelos, exclusivamente en la GPU 0;
inicialmente validar un auxiliar a la vez. Habilitar ambos requiere verificar su
memoria residente combinada y la interferencia con el chat. Solo entonces activar
los aliases correspondientes en las apps.
