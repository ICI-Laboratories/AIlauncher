"""
FastAPI gateway con endpoint /chat que recibe JSON
y valida la API-Key que llega por HTTP header.
"""
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import os

from .config  import Config
from .manager import WorkerPool

app  : FastAPI         = FastAPI(title="LMServ – mini-LM Studio")
cfg  : Config | None   = None        # se inicializa en startup
pool : WorkerPool | None = None

# --------------------------------------------------------------------
# Seguridad mínima: extraemos el header "X-API-Key"
# --------------------------------------------------------------------
def api_key_auth(
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    Dependencia que obtiene el header X-API-Key y lo compara
    con cfg.api_key (que viene de env var API_KEY o fallback "changeme").
    """
    if not cfg:
        # startup no corrió (muy improbable)
        raise HTTPException(status_code=500, detail="Server misconfigured")
    if x_api_key != cfg.api_key:
        raise HTTPException(status_code=401, detail="Bad API key")

# --------------------------------------------------------------------
# Modelo de entrada JSON
# --------------------------------------------------------------------
class ChatRequest(BaseModel):
    prompt     : str
    max_tokens : int | None = None

# --------------------------------------------------------------------
# Eventos de arranque / parada
# --------------------------------------------------------------------
@app.on_event("startup")
async def _startup():
    global cfg, pool
    # Carga de config leyendo env vars: API_KEY, MODEL_PATH, etc.
    cfg  = Config()
    pool = WorkerPool(cfg)
    await pool.start()

@app.on_event("shutdown")
async def _shutdown():
    if pool: # Añadido chequeo por si startup falló y pool no se inicializó
        await pool.shutdown()

# --------------------------------------------------------------------
# Endpoint principal
# --------------------------------------------------------------------
@app.post("/chat", dependencies=[Depends(api_key_auth)])
async def chat(req: ChatRequest):
    """
    Genera texto a partir de `req.prompt` y hace streaming de tokens.
    """
    if not pool: # Chequeo por si pool no está inicializado
        raise HTTPException(status_code=503, detail="Worker pool not available")

    worker = await pool.acquire()

    async def streamer():
        try:
            # La corrección principal está aquí: se eliminó `await` antes de `worker.infer`
            async for tok in worker.infer(req.prompt):
                yield tok
        finally:
            await pool.release(worker)

    return StreamingResponse(streamer(), media_type="text/plain")