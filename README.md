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
| **Instalador Automatizado** | Un script (`setup.sh`) se encarga de compilar `llama.cpp` (para CPU o CUDA) y configurar todo el entorno. |
| **API de Streaming** | El endpoint `POST /chat` devuelve los tokens a medida que se generan, ideal para interfaces web en tiempo real. |
| **Workers Persistentes** | Reutiliza los procesos de `llama-cpp` para atender peticiones con muy baja latencia. |
| **Multi-Worker** | Capacidad para procesar múltiples peticiones de forma simultánea, una por cada worker. |
| **Auto-reparación** | Los workers que fallan se reinician automáticamente para asegurar la disponibilidad del servicio. |
| **Descarga Automática** | Utiliza la nueva funcionalidad de `llama.cpp` para descargar modelos directamente desde Hugging Face al primer uso. |

-----

## 🚀 Guía de Inicio Rápido (Ubuntu)

La instalación está completamente automatizada. Tras clonar el repositorio, solo necesitas ejecutar un comando.

### Paso 1: Clonar el Repositorio

```bash
git clone https://github.com/ICI-Laboratories/AIlauncher.git
cd AIlauncher
```

### Paso 2: Ejecutar el Script de Instalación

Este único comando se encargará de instalar las dependencias del sistema, configurar el entorno de Python, compilar `llama.cpp` y dejar todo listo.

```bash
bash setup.sh
```

*El script te pedirá tu contraseña para instalar paquetes (`apt`) y te preguntará si deseas compilar con soporte para GPU si detecta una.*

-----

## 💻 Cómo Usar el Servidor

Una vez finalizada la instalación, sigue estos pasos para lanzar el servidor:

1.  **Activa el entorno virtual:**

    ```bash
    source env/bin/activate
    ```

2.  **Lanza el servidor con un modelo de Hugging Face:**

    ```bash
    export API_KEY=mysecret
    lmserv serve --model ggml-org/gemma-3-1b-it-GGUF --workers 2
    ```

    > La primera vez que uses un modelo, se descargará y guardará en caché automáticamente. Esto puede tardar varios minutos. Los siguientes arranques serán casi instantáneos.

-----

## 🛠️ Guía de la API para Desarrolladores

Para integrar LMServ en tus aplicaciones, utiliza el siguiente endpoint.

### Endpoint de Chat

  * **Método:** `POST`
  * **Ruta:** `/chat`
  * **URL Completa (ejemplo local):** `http://localhost:8000/chat`

### Cabeceras (Headers)

| Cabecera | Valor de Ejemplo | Obligatorio |
| :--- | :--- | :--- |
| `Content-Type` | `application/json` | **Sí** |
| `X-API-Key` | `mysecret` | **Sí** |

### Cuerpo de la Petición (JSON Body)

El cuerpo de la petición debe ser un objeto JSON. El único campo obligatorio es `prompt`.

| Parámetro | Tipo | Obligatorio | Descripción |
| :--- | :--- | :--- | :--- |
| `prompt` | `string` | **Sí** | El texto o la pregunta para el modelo. |
| `system_prompt` | `string` | No | Instrucción general para guiar el comportamiento del modelo (ej: "Eres un asistente servicial y creativo"). |
| `max_tokens` | `integer` | No | Número máximo de tokens a generar en la respuesta. Por defecto: `128`. |
| `temperature` | `float` | No | Controla la creatividad. Un valor más alto (ej. `0.8`) genera respuestas más variadas. |
| `top_p` | `float` | No | Método de muestreo alternativo a `temperature`. |
| `repeat_penalty`| `float` | No | Penaliza la repetición de palabras. Un valor común es `1.1`. |

### Formato de la Respuesta

La respuesta del servidor es un **flujo de texto plano** (`text/plain`), no un JSON. Los tokens se envían uno por uno a medida que se generan, lo que permite mostrarlos en tiempo real en la aplicación cliente.

### Ejemplos de Peticiones con `curl`

#### Petición Sencilla

```bash
curl -N -H "X-API-Key: mysecret" \
     -H "Content-Type: application/json" \
     -d '{"prompt":"Hola, ¿quién eres?"}' \
     http://localhost:8000/chat
```

#### Petición con Hiperparámetros

```bash
curl -N -H "X-API-Key: mysecret" \
     -H "Content-Type: application/json" \
     -d '{
       "prompt": "Escribe un poema corto sobre los limones de Tecomán.",
       "system_prompt": "Eres un poeta experto en la belleza de Colima.",
       "max_tokens": 100,
       "temperature": 0.75
     }' \
     http://localhost:8000/chat
```

-----

## ✨ Comandos de la CLI

\<details\>
\<summary\>\<code\>lmserv serve\</code\> – Lanza el servidor de API\</summary\>

| Flag | Descripción |
| :--- | :--- |
| `-m, --model TEXT` | **(Requerido)** Ruta a un `.gguf` local o ID de un repositorio de Hugging Face. |
| `-w, --workers INT` | Número de procesos del modelo a ejecutar en paralelo. Por defecto: `2`. |
| `-H, --host TEXT` | Dirección de red en la que el servidor escuchará. Por defecto: `0.0.0.0`. |
| `-p, --port INT` | Puerto HTTP en el que se ejecutará el servidor. Por defecto: `8000`. |

\</details\>

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