from __future__ import annotations

from typing import Any

from ...config import Config
from ...server.pool import WorkerPool
from ..models import GatewayChatRequest, ModelRoute, RuntimeChatResult
from ..runtime import BackendRuntime
from .common import split_system_prompt_and_transcript


class LlamaCppRuntime(BackendRuntime):
    def __init__(self, route: ModelRoute, cfg: Config) -> None:
        super().__init__(route)
        self._runtime_cfg = Config(
            backend="llama_cpp",
            model=route.target,
            catalog_path=cfg.catalog_path,
            default_model_alias=route.name,
            workers=route.workers or cfg.workers,
            host=cfg.host,
            port=cfg.port,
            api_key=cfg.api_key,
            llama_bin=cfg.llama_bin,
            tools_path=cfg.tools_path,
            ollama_base_url=cfg.ollama_base_url,
            request_timeout_s=cfg.request_timeout_s,
            max_tokens=cfg.max_tokens,
            ctx_size=cfg.ctx_size,
            n_gpu_layers=cfg.n_gpu_layers,
            lora=cfg.lora,
            gpu_idx=cfg.gpu_idx,
            vram_cap_mb=cfg.vram_cap_mb,
        )
        self._pool = WorkerPool(self._runtime_cfg)

    async def start(self) -> None:
        await self._pool.start()

    async def shutdown(self) -> None:
        await self._pool.shutdown()

    async def chat(self, request: GatewayChatRequest) -> RuntimeChatResult:
        worker = await self._pool.acquire()
        system_prompt, prompt = split_system_prompt_and_transcript(request.messages)
        chunks: list[str] = []

        try:
            async for token in worker.infer(prompt=prompt, system_prompt=system_prompt):
                chunks.append(token)
        finally:
            await self._pool.release(worker)

        return RuntimeChatResult(
            content="".join(chunks).strip(),
            usage={
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            raw={
                "backend": "llama_cpp",
                "target": self.route.target,
            },
        )

    def describe(self) -> dict[str, Any]:
        data = super().describe()
        data["idle_workers"] = self._pool.free.qsize()
        data["busy_workers"] = len(self._pool.busy)
        return data
