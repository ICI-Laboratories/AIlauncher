# GPU optimized build experiment

## Objetivo

Este experimento evalua si una compilacion de `llama.cpp` ajustada a la GPU
disponible puede mejorar el rendimiento frente al runtime operativo actual.
Debe ejecutarse fuera de produccion: no modifica `/opt/ailauncher`, no cambia
servicios `systemd` y no detiene Ollama, SARA ni `ailauncher`.

En el servidor actual, las GPUs detectadas son NVIDIA RTX A4000. Estas tarjetas
pertenecen a la familia Ampere y normalmente usan arquitectura CUDA `sm_86`.

## Script

El script local es:

```powershell
python .\scripts\gpu_profile_build.py --server-file "C:\Users\pedro\OneDrive\Desktop\server.txt"
```

Por defecto corre en modo auditoria y no compila. Revisa:

- estado de servicios de produccion
- CPU, RAM y disco
- GPUs detectadas por `nvidia-smi`
- toolchain disponible (`git`, `cmake`, `nvcc`)
- arquitectura CUDA propuesta
- plan de compilacion aislada

## Prerrequisitos de compilacion

El metodo recomendado es compilar dentro de un contenedor CUDA. En ese modo el
host solo necesita:

- Docker
- acceso a red para descargar la imagen CUDA y el repositorio `llama.cpp`

El contenedor usa por defecto:

```text
nvidia/cuda:12.8.0-devel-ubuntu24.04
```

Dentro del contenedor se instalan las herramientas de compilacion necesarias
(`git`, `cmake`, `build-essential`) y la compilacion queda en el directorio
experimental montado desde el host.

Para compilar directamente en el host, lo cual no es el camino recomendado, se
requieren:

- `git`
- `cmake`
- compilador C/C++ (`gcc`, `g++` o equivalente)
- `nvidia-smi`
- CUDA toolkit con `nvcc`

Si `cmake` o `nvcc` no estan instalados, el script se detiene antes de compilar.
En ese caso hay dos rutas seguras:

- instalar toolchain en el host dentro de una ventana controlada de mantenimiento
- ejecutar el experimento dentro de un contenedor CUDA `devel`, montando solo el
  directorio experimental

## Compilacion aislada

Para compilar `llama.cpp` en un directorio experimental:

```powershell
python .\scripts\gpu_profile_build.py `
  --server-file "C:\Users\pedro\OneDrive\Desktop\server.txt" `
  --execute-build `
  --use-sudo
```

El modo por defecto es `--build-mode container`. Los limites por defecto son:

```text
--container-cpus 12
--container-memory 16g
```

Estos limites reducen el riesgo de afectar servicios de produccion durante la
compilacion. No se monta `/opt/ailauncher`, no se monta `/etc` y no se detienen
servicios.

`--use-sudo` se usa para poder crear el directorio experimental bajo
`/srv/ai-data`. Aun con sudo, el script mantiene separados los paths de
produccion y reporta el estado de servicios antes y despues.

El resultado queda en:

```text
/srv/ai-data/ailauncher/experiments/llama-cpp-sm-auto-<timestamp>/
```

La compilacion usa:

```text
-DGGML_CUDA=ON
-DCMAKE_CUDA_ARCHITECTURES=<arquitectura detectada>
-DCMAKE_BUILD_TYPE=Release
```

Para RTX A4000, la arquitectura esperada es `86`.

## Benchmark opcional

Si hay un modelo GGUF accesible como archivo regular, puede pasarse asi:

```powershell
python .\scripts\gpu_profile_build.py `
  --server-file "C:\Users\pedro\OneDrive\Desktop\server.txt" `
  --execute-build `
  --model-path "/ruta/remota/modelo.gguf" `
  --bench-prompt 512 `
  --bench-generate 128
```

Nota: los modelos administrados por Ollama no siempre quedan expuestos como un
GGUF con nombre directo. Para comparar formalmente, conviene conservar una copia
GGUF del mismo modelo y cuantizacion usada por el runtime actual.

Para repetir benchmarks con los binarios ya compilados, usa:

```powershell
python .\scripts\remote_llama_bench.py `
  --server-file "C:\Users\pedro\OneDrive\Desktop\server.txt" `
  --use-sudo `
  --run-root "/srv/ai-data/ailauncher/experiments/llama-cpp-sm-auto-20260430T075307Z" `
  --model-path "/srv/ai-data/ollama/models/blobs/sha256-58574f2e94b99fb9e4391408b57e5aeaaaec10f6384e9a699fc2cb43a5c8eabf" `
  --gpu-layers 4 999
```

Este script monta manualmente `/dev/nvidia*` y las librerias del driver dentro
del contenedor. No instala NVIDIA Container Toolkit y no reinicia Docker.

## Variables a reportar

Para el paper, la comparacion debe registrar:

- GPU y arquitectura CUDA
- modelo y cuantizacion
- longitud de contexto
- tokens de prompt y generacion
- tokens por segundo en prompt processing
- tokens por segundo en generacion
- uso maximo de VRAM
- consumo de RAM
- concurrencia usada
- backend evaluado (`llama.cpp`, Ollama o vLLM)

## Criterio de seguridad

El experimento solo es valido si antes y despues de la prueba siguen activos:

- `ailauncher`
- `ollama`
- `docker`
- `sara-backend`
- `sara-backend-tunnel`

Si algun servicio cambia de estado, se debe detener la evaluacion y revisar logs
antes de repetir.

## Ejecuciones registradas

- [2026-04-30: compilacion CUDA containerizada de `llama.cpp`](experiments/2026-04-30-llama-cpp-container-build.md)
- [2026-04-30: optimizacion de `qwen3.6` para SARA](experiments/2026-04-30-qwen36-sara-optimization.md)
- [2026-05-07: validacion final para paper](experiments/2026-05-07-paper-validation.md)

## Optimizacion sin migrar de backend

Una observacion del servidor actual es que Ollama puede escoger un contexto
predeterminado muy grande. En este servidor reporto `32768` tokens de contexto,
lo que reduce el numero de capas que caben en GPU para modelos grandes. Antes
de migrar a otro backend conviene probar un perfil con menor contexto:

```json
{
  "settings": {
    "think": false,
    "keep_alive": "10m",
    "options": {
      "num_ctx": 4096
    }
  }
}
```

El prototipo local ya soporta `settings.options` para enviar estos parametros a
Ollama por solicitud. El catalogo experimental esta en
[`deploy/models.server.experimental.json`](../deploy/models.server.experimental.json).

Para el modelo base actual de la app se creo ademas un derivado de Ollama:

```text
qwen3.6-sara:opt
```

Ese modelo hereda `qwen3.6:35b` y fija `num_ctx=4096` y `num_gpu=24`. Es el
perfil recomendado para produccion mientras se valida una ruta `llama.cpp`
separada.

La validacion final del 2026-05-07 usa ese mismo modelo derivado, pero el
catalogo productivo envia por solicitud `num_gpu=41`, `num_batch=512`,
`num_thread=24` y `keep_alive=24h`. Ese es el perfil que debe considerarse
vigente para SARA.

No se recomienda poner `num_gpu=999` en produccion sin una prueba controlada.
En una corrida manual, Ollama logro cargar `qwen3:30b` con 49/49 capas en GPU
cuando detecto ambas RTX A4000; en otra corrida detecto solo una GPU y fallo
con `memory layout cannot be allocated with num_gpu = 999`.
