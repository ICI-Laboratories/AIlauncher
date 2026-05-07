# llama.cpp CUDA container build - 2026-04-30

## Objetivo

Compilar una version experimental de `llama.cpp` ajustada a las GPUs del
servidor sin modificar servicios de produccion.

## Entorno

- Servidor: `fimenibblegpu`
- Sistema operativo: Ubuntu 24.04.4 LTS
- Virtualizacion: VMware
- CPU: 24 vCPU Intel Xeon E5-2640
- RAM: 19 GiB
- GPU: 2 x NVIDIA RTX A4000
- Compute capability detectada: `8.6`
- Arquitectura CUDA usada: `sm_86`
- Driver NVIDIA: 570.211.01
- CUDA soportado por driver: 12.8

## Metodo

La compilacion se ejecuto con:

```powershell
python .\scripts\gpu_profile_build.py `
  --server-file "C:\Users\pedro\OneDrive\Desktop\server.txt" `
  --execute-build `
  --use-sudo
```

El script uso el modo `container`, con:

```text
image: nvidia/cuda:12.8.0-devel-ubuntu24.04
cpus: 12
memory: 16g
cmake: -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=86 -DCMAKE_BUILD_TYPE=Release
```

El host no tenia toolchain CUDA/C++ instalado (`cmake`, `gcc`, `g++`, `nvcc`),
por lo que esas dependencias se resolvieron dentro del contenedor.

## Resultado

La compilacion finalizo correctamente.

```text
run_root=/srv/ai-data/ailauncher/experiments/llama-cpp-sm-auto-20260430T075307Z
run_log=/srv/ai-data/ailauncher/experiments/llama-cpp-sm-auto-20260430T075307Z/run.log
```

Binarios generados:

```text
/srv/ai-data/ailauncher/experiments/llama-cpp-sm-auto-20260430T075307Z/build/bin/llama-cli
/srv/ai-data/ailauncher/experiments/llama-cpp-sm-auto-20260430T075307Z/build/bin/llama-bench
/srv/ai-data/ailauncher/experiments/llama-cpp-sm-auto-20260430T075307Z/build/bin/llama-server
```

Version compilada:

```text
llama.cpp commit: 27aef3dd91e7cde049e7c242dbf6c8fe86574d01
short: 27aef3d
build compiler: GNU 13.3.0
```

## Estado de produccion

Antes y despues de la compilacion se verifico:

```text
system=running
ailauncher=active
ollama=active
docker=active
sara-backend=active
sara-backend-tunnel=active
systemctl --failed: 0 unidades fallidas
```

Despues del experimento, `ailauncher` respondio correctamente:

```text
health: ok
chat test: OK
tokens: 18
```

## Observaciones

Docker no tiene NVIDIA Container Toolkit configurado. Por eso el contenedor
puede compilar con CUDA, pero no puede ejecutar inferencia GPU directamente.
Para enlazar dentro del contenedor se usaron los stubs de CUDA. Despues se
valido que una ejecucion experimental puede detectar las GPUs mediante montaje
manual de `/dev/nvidia*` y librerias del driver NVIDIA, sin instalar NVIDIA
Container Toolkit ni reiniciar Docker.

Durante la prueba posterior, Ollama necesito alrededor de 141 segundos para
cargar `qwen3.6:35b` despues de haber estado descargado de GPU. Luego la
peticion corta respondio `OK`.

## Benchmarks exploratorios

Los benchmarks siguientes usan el blob GGUF de `qwen3:30b` administrado por
Ollama:

```text
/srv/ai-data/ollama/models/blobs/sha256-58574f2e94b99fb9e4391408b57e5aeaaaec10f6384e9a699fc2cb43a5c8eabf
```

### llama.cpp experimental

Comando base:

```text
llama-bench -m /model.gguf -p 64 -n 16 -r 1
```

Resultados:

| Backend | Modelo | GPU layers | Prompt t/s | Generacion t/s |
|---|---:|---:|---:|---:|
| llama.cpp CUDA sm_86 | qwen3:30b Q4_K_M | 4 | 13.18 | 0.67 |
| llama.cpp CUDA sm_86 | qwen3:30b Q4_K_M | 999 | 866.35 | 93.31 |

La corrida con `-ngl 999` cargo el modelo con offload alto y mostro una mejora
aproximada de 139x en generacion frente a la corrida con 4 capas GPU. Esta
comparacion es exploratoria: usa prompts pequenos y no sustituye una evaluacion
multiusuario, pero confirma que el cuello de botella principal era la falta de
offload completo a GPU.

### Ollama directo

Con `qwen3:30b`, `num_ctx=4096` y sin forzar `num_gpu`, Ollama respondio pero
quedo en una mezcla CPU/GPU:

```text
processor: 68%/32% CPU/GPU
context: 4096
wall_s: 58.95
load_s: 42.82
prompt_tps: 5.02
generation_tps: 1.27
```

En logs previos, una corrida con `num_gpu=999` y ambas GPUs detectadas logro
`49/49` capas en GPU para `qwen3:30b`; la segunda solicitud caliente respondio
en aproximadamente `0.79 s`. Sin embargo, una corrida posterior detecto solo
una GPU y fallo con:

```text
memory layout cannot be allocated with num_gpu = 999
```

Por eso no se recomienda desplegar `num_gpu=999` directamente en produccion sin
resolver antes la estabilidad de deteccion multi-GPU en Ollama.

## Lectura provisional

La migracion directa a `llama.cpp` no debe hacerse todavia para produccion,
pero el resultado justifica crear una ruta experimental controlada en
LMLauncher. La opcion mas prudente es:

1. mantener Ollama en produccion
2. habilitar `settings.options` en LMLauncher para pruebas con `num_ctx`
3. probar `qwen3:30b` en un puerto alterno con `llama-server`
4. comparar latencia real de SARA antes de migrar trafico
