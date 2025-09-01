# LMServ – Servidor Ligero para LLMs Locales

> **Instalación con un solo comando. Servidor con un solo comando. Cero dependencias de la nube.**

LMServ encapsula el rapidísimo backend de **`llama.cpp`** con una amigable CLI de **Typer** y un servidor de streaming **FastAPI**, permitiéndote ejecutar modelos de lenguaje modernos completamente en tu propio hardware, desde una laptop hasta un pequeño servidor casero.

\<p align="center"\>
\<img src="docs/diagram.svg" width="680"
alt="Arquitectura: CLI → FastAPI → WorkerPool → llama-cli" /\>
\</p\>

-----

## 🔥 Características Principales

| Característica | Descripción |
| :--- | :--- |
| **Instalador Multi-Distro** | Un script (`setup.sh`) detecta tu SO (Ubuntu, Fedora, Arch) y compila `llama.cpp` (CPU o CUDA). |
| **Uso de Herramientas (Agente)** | Define herramientas en JSON; el modelo puede decidir usarlas en un bucle de razonamiento. |
| **Gramáticas Forzadas (GBNF)** | Genera automáticamente gramáticas para forzar al modelo a producir JSON válido para las llamadas a herramientas. |
| **Workers Persistentes** | Reutiliza los procesos de `llama-cpp` para atender peticiones con muy baja latencia. |
| **Multi-Worker** | Capacidad para procesar múltiples peticiones de forma simultánea. |
| **Descarga Automática** | Descarga modelos de Hugging Face al primer uso. |

-----

## 🚀 Guía de Inicio Rápido (Linux y WSL2)

### Paso 1: Instalación

El script de instalación automatizada se encarga de todo.
```bash
git clone https://github.com/ICI-Laboratories/AIlauncher.git
cd AIlauncher
bash setup.sh
```

### Paso 2: Uso Básico del Servidor

```bash
# Activa el entorno virtual
source env/bin/activate

# Define una clave de API para proteger tu servidor
export API_KEY=my-super-secret-key

# Lanza el servidor con un modelo de Hugging Face
lmserv serve --model ggml-org/gemma-3-1b-it-GGUF
```

### Paso 3: Uso con Herramientas (Modo Agente)

1.  **Crea un fichero de herramientas `tools.json`:**
    ```json
    {
      "tools": [
        {
          "name": "get_weather",
          "description": "Obtiene el clima actual para una ciudad.",
          "parameters": {
            "type": "object",
            "properties": {
              "city": { "type": "string", "description": "La ciudad, ej: 'San Francisco, CA'" },
              "unit": { "type": "string", "enum": ["celsius", "fahrenheit"] }
            },
            "required": ["city"]
          }
        }
      ]
    }
    ```
2.  **Lanza el servidor con el flag `--tools`:**
    ```bash
    lmserv serve \
      --model TheBloke/Mistral-7B-Instruct-v0.2-GGUF \
      --tools tools.json \
      --n-gpu-layers 35
    ```
3.  **Realiza una petición que requiera la herramienta:**
    ```bash
    curl -H "X-API-Key: my-super-secret-key" \
         -H "Content-Type: application/json" \
         -d '{"prompt":"¿Qué clima hace en Tokyo?"}' \
         http://localhost:8000/chat
    ```
    El servidor devolverá la respuesta final del modelo después de haber llamado a la herramienta `get_weather`.

-----

## 🛠️ Guía de la API para Desarrolladores

### Flujo de Razonamiento y Herramientas

Cuando se usa el flag `--tools`, el endpoint `/chat` cambia su comportamiento:
1.  El servidor recibe el `prompt`.
2.  El modelo genera un JSON con su "pensamiento" (`thought`) y, opcionalmente, una llamada a una herramienta (`tool_call`).
3.  Si hay una `tool_call`, el servidor la ejecuta.
4.  El resultado de la herramienta se re-inserta en el contexto del modelo.
5.  El proceso se repite hasta que el modelo genera una respuesta final (un `thought` sin `tool_call`).
6.  La respuesta final (`thought`) se devuelve al cliente.

Este ciclo convierte a LMServ en un **agente básico** capaz de usar herramientas para responder preguntas.

### Endpoint de Chat

*   **Método:** `POST`
*   **Ruta:** `/chat`
*   **Cuerpo (JSON):** `{ "prompt": "Tu pregunta aquí" }`
*   **Respuesta (`text/plain`):** La respuesta final del modelo después del ciclo de razonamiento.

-----

## ✨ Comandos de la CLI (`lmserv serve`)

| Parámetro | Flag | Descripción | Panel |
| :--- | :--- | :--- | :--- |
| **Modelo** | `-m`, `--model` | **(Requerido)** ID de Hugging Face o ruta a un fichero `.gguf`. | Servidor |
| **Herramientas** | `--tools` | **(Opcional)** Ruta al fichero JSON que define las herramientas. | Servidor |
| **Workers** | `-w`, `--workers` | Número de workers a ejecutar en paralelo. | Servidor |
| **Host/Puerto** | `-H`, `-p` | Interfaz y puerto de red del servidor. | Servidor |
| **Capas en GPU** | `--n-gpu-layers` | Número de capas del modelo a descargar en la VRAM. | Modelo |
| **Tamaño Contexto**| `--ctx-size` | Tamaño del contexto del modelo en tokens. | Modelo |
| **Adaptador LoRA**| `--lora` | Ruta a un adaptador LoRA (`.gguf`) para aplicar al modelo. | Modelo |

</details>

\<details\>
\<summary\>\<code\>lmserv install llama\</code\> – Compila el motor llama.cpp\</summary\>

| Flag | Descripción |
| :--- | :--- |
| `--output-dir PATH` | Directorio donde se clonará y compilará `llama.cpp`. Por defecto: `build/`. |
| `--cuda / --no-cuda` | Activa o desactiva la compilación con soporte para GPU NVIDIA. |

\</details\>

-----

## 📜 Licencia

Este proyecto se distribuye bajo la **Licencia MIT**.