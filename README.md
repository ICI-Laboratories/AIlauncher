# LMServ · mini-LM Studio

> **lightweight local LLM service – _click-to-run_**  
> CLI + FastAPI + mDNS discovery · 100 % Python (C++ hot-paths opcionales)


---

## Tabla de contenidos
1. [Motivación](#motivación)
2. [Características](#características)
3. [Instalación rápida](#instalación-rápida)
4. [Comandos principales](#comandos-principales)
5. [Estructura del código](#estructura-del-código)
6. [Variables de entorno](#variables-de-entorno)
7. [Roadmap](#roadmap)
8. [Contribuir](#contribuir)
9. [Licencia](#licencia)

---

## Motivación

En laboratorios y pymes **no conviene** pagar plataformas cloud para servir modelos
de lenguaje grandes.  
LMServ expone una REST API _OpenAI-compatible_ ejecutando `llama.cpp`
en la GPU/CPU local y descubre automáticamente otros nodos dentro
de la red (al estilo Ollama o LM Studio).

<p align="center">
  <img src="docs/diagram.svg" width="680" alt="Arquitectura básica: CLI → FastAPI → WorkerPool → llama-cli" />
</p>

---

## Características

| Módulo | Descripción |
|--------|-------------|
| **CLI (Typer)** | `lmserv serve / install / discover / llama …` |
| **FastAPI** | Endpoint `POST /chat`, streaming token-a-token |
| **WorkerPool** | Múltiples procesos `llama-cli` reaprovechados |
| **mDNS discovery** | Anuncia/descubre `_lmserv._tcp.local.` sin configurar |
| **Instalador** | Compila `llama.cpp` y baja `.gguf` verificados |
| **Hot-paths C++** | Opcional via `pybind11` (sampling, tokenizer) |
| **Empaquetado** | PyInstaller one-file + Dockerfile _(pendiente)_ |

---

## Instalación rápida

```bash
# 1. clonar repositorio
git clone https://github.com/tu-usuario/lmserv.git(falta!)
cd lmserv

# 2. entorno Python 3.10+
python -m venv env && source env/bin/activate
pip install -U pip wheel && pip install -e .

# 3. compilar llama.cpp (CUDA por defecto)
lmserv install llama --output-dir build/

# 4. descargar modelo de prueba
lmserv install models gemma-2b --target-dir models/
````

---

## Comandos principales

```bash
# lanzar API + 3 workers (http://localhost:8000/chat)
lmserv serve --model-path models/gemma-2b.gguf --workers 3

# listar nodos LMServ en la LAN
lmserv discover --timeout 3

# invocar directamente llama-cli con cualquier flag
lmserv llama --help
```

---

## Estructura del código

```
lmserv/
├── cli.py                ← entrada Typer
├── config.py             ← configuración central (ENV + sane defaults)
├── server/               ← API, seguridad y workers
│   ├── api.py
│   ├── pool.py
│   ├── security.py
│   └── workers/
│       ├── llama.py      ← proceso externo llama-cli
│       ├── utils.py
│       └── cpp_bridge.py ← bindings opcionales C++
├── discovery/            ← mDNS + registro en memoria
├── install/              ← build de llama.cpp + fetch de modelos
└── docs/                 ← diagramas y documentación de alto nivel
tests/                    ← (pendiente) pytest-asyncio
```

Cada sub-carpeta incluye su propio **README.md** con cambios
recientes y tareas pendientes.

---

## Variables de entorno

| Variable     | Valor por defecto   | Uso                     |
| ------------ | ------------------- | ----------------------- |
| `MODEL_PATH` | `models/gemma.gguf` | Ruta al modelo          |
| `WORKERS`    | `2`                 | Nº procesos llama-cli   |
| `HOST`       | `0.0.0.0`           | Interfaz FastAPI        |
| `PORT`       | `8000`              | Puerto HTTP             |
| `API_KEY`    | `changeme`          | Token simple de acceso  |
| `MAX_TOKENS` | `128`               | Límite de generación    |
| `LLAMA_BIN`  | *(auto-detect)*     | Ejecutable llama-cli    |
| `LOG_LEVEL`  | `INFO`              | Nivel global de logging |

---

## Roadmap

* [x] Refactor ✂︎ archivos ≤ 300 líneas
* [ ] PyInstaller one-file (`dist/`)
* [ ] Dockerfile con soporte GPU (`--gpus all`)
* [ ] Selector de modelo según VRAM/CPU
* [ ] Benchmarks automáticos en CI
* [ ] Autenticación mTLS opcional
* [ ] UI web minimal (React + shadcn)

---

## Contribuir

1. Crea un *fork* y una rama descriptiva `feat/nombre-claro`.
2. Asegúrate de que **ruff**, **black** y **pytest** pasen:

   ```bash
   ruff check . && black --check . && pytest -q
   ```
3. Abre un Pull Request; revisaremos en menos de 48 h.

Para grandes cambios abre primero una *issue* para coordinar esfuerzos.

---

## Licencia

MIT © 2024 — Tu Nombre / Colaboradores
Ver `LICENSE` para más detalles.

