"""Un wrapper asíncrono alrededor de `llama.cpp` (llama-cli)."""
from __future__ import annotations
import asyncio, signal, uuid
from subprocess import Popen, PIPE

class LlamaWorker:
    def __init__(self, model_path: str, gpu_idx: int):
        self.id = uuid.uuid4().hex[:8]
        self.model_path = model_path
        self.gpu_idx = gpu_idx
        self.proc: Popen | None = None

    async def spawn(self):
        # Nota: usa JSON streaming para parsear más fácil si quieres.
        self.proc = Popen([
            "./build/bin/llama-cli",
            "-m", self.model_path,
            "-ngl", "100",
            "--json"   # salida estructurada
        ], stdin=PIPE, stdout=PIPE, text=True, bufsize=1)
        # pequeña pausa para que el modelo se copie a VRAM
        await asyncio.sleep(1)

    async def infer(self, prompt: str):
        """Genera tokens y los entrega en un generador async."""
        assert self.proc and self.proc.stdin and self.proc.stdout, "Worker no iniciado"
        self.proc.stdin.write(prompt + "\n###END###\n")
        self.proc.stdin.flush()
        # Stream línea a línea (o token a token si cambias el formato)
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, self.proc.stdout.readline)
            if not line:
                break
            yield line.rstrip("\n")

    async def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                await asyncio.to_thread(self.proc.wait, timeout=10)
            except Exception:
                self.proc.kill()