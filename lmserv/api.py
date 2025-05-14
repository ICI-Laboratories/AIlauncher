"""FastAPI que expone `/chat` en streaming."""
import os, asyncio
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from .config import Config
from .manager import WorkerPool

cfg = Config()   # se llena desde variables de entorno
app = FastAPI(title="lmserv")

pool = WorkerPool(cfg)

@app.on_event("startup")
async def _startup():
    await pool.start()

@app.on_event("shutdown")
async def _shutdown():
    await pool.shutdown()

def _auth(x_api_key: str = Depends(lambda: os.getenv("API_KEY", "changeme"))):
    if x_api_key != cfg.api_key:
        raise HTTPException(401, "Bad API key")

@app.post("/chat", dependencies=[Depends(_auth)])
async def chat(prompt: str):
    worker = await pool.acquire()

    async def streamer():
        async for token in worker.infer(prompt):
            yield token
        await pool.release(worker)

    return StreamingResponse(streamer(), media_type="text/plain")