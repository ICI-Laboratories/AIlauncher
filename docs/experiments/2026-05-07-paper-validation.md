# Paper validation run - 2026-05-07

## Objetivo

Validar el estado productivo de `ailauncher` antes de cerrar el borrador CIREDII
2026. La prueba cubre salud del gateway, autenticacion, salida estructurada,
generacion larga, concurrencia ligera y estabilidad de servicios despues de la
carga.

## Entorno

- Servidor: `fimenibblegpu`
- Sistema operativo: Ubuntu 24.04.4 LTS
- Virtualizacion: VMware
- CPU: 24 vCPU Intel Xeon E5-2640
- RAM: 19 GiB
- GPU: 2 x NVIDIA RTX A4000
- Gateway: `ailauncher` en puerto `8009`
- Backend activo: Ollama
- Modelo: `qwen3.6-sara:opt`
- Contexto: `4096`
- Perfil de catalogo: `think=false`, `keep_alive=24h`, `num_gpu=41`,
  `num_batch=512`, `num_thread=24`

Antes de la prueba, `ollama ps` reporto el modelo como `100% GPU`, contexto
`4096` y permanencia de 24 horas.

## Artefactos remotos

```text
/srv/ai-data/ailauncher/experiments/paper-validation-final-20260507T064642Z
/srv/ai-data/ailauncher/experiments/paper-validation-final-20260507T064642Z/results.jsonl
/srv/ai-data/ailauncher/experiments/paper-validation-final-20260507T064642Z/summary.json
/srv/ai-data/ailauncher/experiments/paper-validation-final-20260507T064642Z/meta.txt
```

El archivo `results.jsonl` guarda metricas, hashes de contenido y validaciones
booleanas. No guarda credenciales ni prompts completos.

## Estado de servicios

Antes y despues de la prueba:

```text
system=running
ailauncher=active
ollama=active
docker=active
sara-backend=active
sara-backend-tunnel=active
systemctl --failed: 0 unidades fallidas
```

Endpoints:

```text
GET /health: 200
GET /v1/models con API key: 200
```

## Resultados

| Prueba | n | Latencia media | Rango | Tokens/s medio | Resultado |
|---|---:|---:|---:|---:|---|
| `sanity_ok` | 3 | 1.027 s | 1.009-1.050 s | 1.95 | `OK` exacto 3/3 |
| `json_schema` | 3 | 1.597 s | 1.456-1.721 s | 13.21 | JSON valido 3/3 |
| `json_object` | 3 | 1.739 s | 1.632-1.830 s | 12.10 | JSON valido 3/3 |
| `controlled_256` | 3 | 6.826 s | 6.584-7.004 s | 37.53 | HTTP 200 3/3 |
| `assessment_like_512` | 2 | 12.718 s | 12.656-12.779 s | 40.26 | HTTP 200 2/2 |
| `concurrent_2` | 2 | 3.815 s | 2.795-4.835 s | 23.44 | HTTP 200 2/2 |

La prueba concurrente de dos solicitudes tuvo una duracion total de `4.844 s`.
Todas las respuestas fueron servidas por `sara-main`.

## Observaciones

Una prueba exploratoria previa de `json_schema`, con instruccion menos
restrictiva, respondio HTTP 200 pero no produjo JSON parseable. Al agregar una
instruccion de sistema explicita para responder solo JSON, `json_schema` y
`json_object` pasaron 3/3. Para el paper, esto debe reportarse como validacion
controlada de salida estructurada, no como garantia absoluta ante cualquier
prompt.

La primera solicitud del dia, antes de que el modelo estuviera caliente, tomo
`53.319 s`. Despues, con `keep_alive=24h` y el modelo residente en GPU, las
solicitudes cortas estuvieron alrededor de 1 a 2 segundos y las generaciones de
256 a 512 tokens se mantuvieron alrededor de 37 a 40 tokens/s de pared.

## Lectura para el paper

El servidor productivo ya no corresponde al perfil conservador `num_gpu=24`.
El estado validado usa `num_gpu=41` y mantiene `qwen3.6-sara:opt` cargado en
ambas RTX A4000. El paper debe citar esta corrida como validacion productiva y
mantener las pruebas de `llama.cpp` como evidencia exploratoria separada.
