import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

# Importa los módulos y objetos que vamos a manipular
from lmserv.server import api as server_api
from lmserv.server.workers.llama import LlamaWorker

# Headers de prueba
_HEADERS = {"X-API-Key": "changeme"}


# --- SOLUCIÓN DEFINITIVA: Usar monkeypatch de forma más directa ---

@pytest.fixture(autouse=True)
def mock_api_dependencies(monkeypatch):
    """
    Este fixture se ejecuta automáticamente para cada prueba en este archivo.
    "Engaña" a la API para que no dependa de archivos reales o procesos externos.
    """
    # 1. Crea un worker falso con un método 'infer' falso
    mock_worker = AsyncMock(spec=LlamaWorker)
    mock_worker.infer.return_value = (i for i in ["Respuesta ", "de la ", "IA"]) # Un generador

    # 2. Crea un "pool de workers" falso
    mock_pool = AsyncMock()
    mock_pool.acquire.return_value = mock_worker # El pool devuelve el worker falso

    # 3. Reemplaza directamente las variables globales en el módulo de la API
    monkeypatch.setattr(server_api, "_pool", mock_pool)
    monkeypatch.setattr(server_api, "_cfg", "dummy_config") # No necesita ser una config real ahora


# --- Las pruebas ---

@pytest.mark.asyncio
async def test_health_ok():
    """Verifica que /health funcione correctamente."""
    transport = ASGITransport(app=server_api.app)
    async with AsyncClient(base_url="http://test", transport=transport) as client:
        r = await client.get("/health")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_chat_stream():
    """Verifica que /chat ahora devuelva 200 OK y el contenido esperado."""
    transport = ASGITransport(app=server_api.app)
    async with AsyncClient(base_url="http://test", transport=transport) as client:
        r = await client.post(
            "/chat",
            headers={**_HEADERS, "Content-Type": "application/json"},
            json={"prompt": "¿Quién eres?", "max_tokens": 16},
        )
        assert r.status_code == 200
        content = await r.aread()
        assert "Respuesta de la IA" in content.decode()


@pytest.mark.asyncio
async def test_bad_api_key():
    """Verifica que una API key incorrecta sea rechazada con 401."""
    transport = ASGITransport(app=server_api.app)
    async with AsyncClient(base_url="http://test", transport=transport) as client:
        r = await client.post(
            "/chat",
            headers={"X-API-Key": "bad-key", "Content-Type": "application/json"},
            json={"prompt": "test"},
        )
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_missing_prompt():
    """Verifica que una petición sin 'prompt' devuelva 422."""
    transport = ASGITransport(app=server_api.app)
    async with AsyncClient(base_url="http://test", transport=transport) as client:
        r = await client.post(
            "/chat",
            headers={**_HEADERS, "Content-Type": "application/json"},
            json={"max_tokens": 16},
        )
        assert r.status_code == 422