
# LMServ: Lightweight Local LLM Service

LMServ is a powerful yet lightweight service that allows you to run and interact with local language models via a simple command-line interface and a robust API. It is designed for developers and researchers who need a fast, local, and customizable inference server without the overhead of heavy-duty platforms.

The service uses `llama.cpp` as its backend engine, providing high-performance inference on both CPU and GPU.

\<p align="center"\>
\<img src="docs/diagram.svg" width="680" alt="Architecture: CLI → FastAPI → WorkerPool → llama-cli" /\>
\</p\>

-----

## Features

  * **Powerful CLI (`Typer`)**: A user-friendly command-line interface to manage all aspects of the service, from installation to serving models.
  * **High-Performance API (`FastAPI`)**: A fast, asynchronous API endpoint (`/chat`) for streaming token-by-token responses from the language model.
  * **Concurrent Worker Pool**: Manages multiple `llama.cpp` processes to handle simultaneous requests efficiently.
  * **Automated Installer**: Includes commands to automatically clone and compile `llama.cpp` with CUDA support, and to download popular GGUF models from a catalog.
  * **LAN Discovery (`mDNS`)**: Automatically discovers other `LMServ` instances running on the same local network.
  * **Flexible Configuration**: Configure the service via command-line arguments or environment variables.

-----

## Installation Guide

Follow these steps to get `LMServ` up and running on your local machine.

### Step 1: Clone the Repository

```bash
git clone https://github.com/ICI-Laboratories/AIlauncher.git
cd AIlauncher
```

### Step 2: Set Up a Virtual Environment

It's highly recommended to use a virtual environment to manage dependencies.

```bash
# Create the environment
python -m venv env

pip install -r requirements.txt

# Activate it (Windows)
.env\Scripts\activate

# Activate it (Linux/macOS)
# source env/bin/activate
```

### Step 3: Install Dependencies

Install the project and its Python dependencies. The `-e .` command installs it in "editable" mode.

```bash
pip install -e .
```

### Step 4: Compile `llama.cpp`

This command clones the `llama.cpp` repository into a `build/` directory and compiles the necessary binaries. It will attempt to build with CUDA support by default.

If is not working whithin the vsc terminal you should use x64 Native Tools

```bash
python -m lmserv.cli install llama --output-dir build/
```

### Step 5: Download a Model

You can use a model you already have, or download one from the built-in catalog.

```bash
# Example: Download the gemma-2b model
python -m lmserv.cli install models gemma-2b --target-dir models/
```

-----

## How to Run the Server

Once everything is installed, you can start the API server. You must provide the path to your model file and the path to the compiled `llama-cli.exe` binary.

```bash
python -m lmserv.cli serve --model-path "path/to/your/model.gguf" --llama-bin "path/to/your/build/build-cuda/bin/llama-cli.exe"
```

**Example:**

```bash
python -m lmserv.cli serve --model-path "D:\lmmodels\gemma-3-1b-it-GGUF\gemma-3-1b-it-Q8_0.gguf" --llama-bin "C:\Users\pedro\Documents\GitHub\AIlauncher\build\build-cuda\bin\llama-cli.exe"
```

The server will start and be available at `http://localhost:8000`.

-----

## Command Reference

### `serve`

Starts the main API server.

  * `--model-path, -m`: (Required) Path to the `.gguf` model file.
  * `--llama-bin`: (Required) Path to the compiled `llama-cli` executable.
  * `--workers, -w`: Number of parallel worker processes (default: 2).
  * `--host, -H`: Host interface to listen on (default: `0.0.0.0`).
  * `--port, -p`: Port to listen on (default: 8000).
  * `--max-tokens`: Default maximum tokens for generation (default: 128).

### `install`

Contains sub-commands for installation tasks.

  * **`install llama`**: Compiles `llama.cpp`.
      * `--output-dir, -o`: Directory to store the build (default: `build/`).
      * `--cuda / --no-cuda`: Compile with or without CUDA support (default: `--cuda`).
  * **`install models`**: Downloads models from the catalog.
      * `names...`: One or more model names to download (e.g., `gemma-2b`, `phi3-mini`).
      * `--target-dir, -d`: Directory to save the models (default: `models/`).

### `discover`

Searches for other `LMServ` nodes on the local network.

  * `--timeout, -t`: Seconds to search for nodes (default: 5).

### `llama`

A direct passthrough to the `llama-cli` executable. Allows you to run any `llama-cli` command directly.

**Example:**

```bash
python -m lmserv.cli llama --version
```

### `update`

Pulls the latest changes from the Git repository and reinstalls the package.

-----

## API Usage

You can interact with the server by sending `POST` requests to the `/chat` endpoint.

**Example using `curl`:**

```bash
curl -X POST http://localhost:8000/chat \
-H "Content-Type: application/json" \
-H "X-API-Key: changeme" \
-d '{
    "prompt": "Tell me a short story about a robot who learns to dream.",
    "system_prompt": "You are a master storyteller.",
    "temperature": 0.9
}'
```

**Example using the interactive client (`pruebas.py`):**

```bash
python pruebas.py
```
