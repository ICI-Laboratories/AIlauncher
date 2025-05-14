# AIlauncher
Large Language Models Tiny Launcher: A tool for deploying large language models (LLMs) in production and research environments. Designed with a focus on academic research, it enables efficient execution and accessibility for analysis and experimentation.


# lmserv

Servicio ligero que lanza varias instancias de `llama.cpp` en una GPU y expone un endpoint `/chat`.

```bash
# requisitos básicos
sudo apt install git build-essential cmake ninja-build python3-pip -y
pip install uvicorn[standard] fastapi typer[all] pynvml loguru

# clonar + instalar (compila llama.cpp con CUDA)
git clone https://github.com/tu-usuario/lmserv.git
cd lmserv && pip install .

# lanzar
python -m lmserv serve --model-path models/gemma.gguf --workers 3 --port 8000