# `server/workers` – motores de inferencia

Cada sub-módulo aquí implementa **un tipo de worker** que el
`WorkerPool` puede lanzar y reutilizar.  El contrato común
permite cambiar el backend sin tocar la capa HTTP:

```python
async def spawn()              -> None                    # levantar recurso
async def infer(prompt: str)   -> AsyncIterator[str]      # streaming tokens
async def stop()               -> None                    # liberar recurso
````

## Árbol actual

```
workers/
├── __init__.py
├── llama.py        ← spawns llama-cli (referencia)
├── cpp_bridge.py   ← bindings pybind11 (hot-paths)
└── utils.py        ← _stream_reader y helpers compartidos
```

### 1. `llama.LlamaWorker`

* **Proceso externo**: `llama-cli -i --interactive-first`
* Lee stdout/stderr con `asyncio`, detecta *reverse-prompt* marker
  `<|LMSERV_USER_INPUT_START|>` para saber dónde termina la respuesta.
* ≤ 300 líneas para facilitar debug; algoritmos pesados → C++.

### 2. `cpp_bridge`

* Carga `lmserv_cpp.*.so` si existe (compilado con pybind11).
  Implementa `sample_top_p` y `tokenize` en C++.
* Transparente: si la librería no está, cae en versión Python.

### 3. `utils._stream_reader`

* Corrutina que empuja líneas de un `TextIO` a una `asyncio.Queue`.
  Detecta EOF y errores, avisando al *worker* vía `Event`.

## Como añadir un nuevo backend

1. Crea `workers/mlc.py` (por ejemplo) implementando la interfaz.
2. Regístralo opcionalmente en `workers.__init__` para exportarlo.
3. Ajusta `WorkerPool` si quieres mezclar distintos tipos en el mismo pool.

## Cambios recientes

| Fecha        | Autor       | Descripción                             |
| ------------ | ----------- | --------------------------------------- |
| 2024-06-\*\* | @tu-usuario | 🚀 Añadido `cpp_bridge` con stub Python |

## Pendiente

* [ ] Pool heterogéneo (CPU/GPU mix).
* [ ] Supervisor que reinicie worker lento (< tokens/s umbral).
* [ ] Integración con `vLLM` o `TensorRT-LLM`.

