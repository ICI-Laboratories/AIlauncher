"""Configuration must never redirect an unknown auxiliary model to chat."""
from dataclasses import replace
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from lmserv.server.routes import BackendRoute, build_routes, load_auxiliary_routes, resolve_route


def config(*auxiliary):
    return SimpleNamespace(
        backend_url='http://chat:8080/v1', backend_model='qwen-local', aliases=('sara-main', 'qwen-local'),
        max_inflight=6, max_queue=32, per_app_inflight=2, queue_timeout=60,
        request_timeout=300, max_output_tokens=2048, max_body_bytes=16 * 1024 * 1024,
        max_context_tokens=24576, auxiliary_routes=auxiliary,
    )


def ocr(**overrides):
    return BackendRoute(**dict(name='ocr', operation='chat', backend_url='http://ocr:8080/v1',
                               backend_model='glm-ocr', aliases=('ocr',), **overrides))


def test_legacy_chat_settings_remain_default_and_unknown_never_falls_back():
    routes = build_routes(config())
    route, alias = resolve_route(routes, None, 'chat')
    assert route.name == 'chat' and alias == 'sara-main'
    assert route.max_inflight == 6
    for model in ('ocr', 'bge-m3', 'misspelled', ''):
        with pytest.raises(HTTPException) as exc:
            resolve_route(routes, model, 'chat')
        assert exc.value.status_code == 404


def test_explicit_model_selects_backend_and_operation():
    embedding = BackendRoute(name='embeddings', operation='embeddings', backend_url='http://embed:8080/v1',
                             backend_model='bge-m3-real', aliases=('bge-m3',))
    routes = build_routes(config(ocr(), embedding))
    assert resolve_route(routes, 'ocr', 'chat')[0].backend_model == 'glm-ocr'
    assert resolve_route(routes, 'bge-m3', None)[0] == embedding
    with pytest.raises(HTTPException) as exc:
        resolve_route(routes, 'bge-m3', 'chat')
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        resolve_route(routes, None, 'embeddings')
    assert exc.value.status_code == 422


def test_duplicate_aliases_route_names_or_engine_urls_are_rejected():
    for aux in (replace(ocr(), aliases=('sara-main',)), replace(ocr(), backend_url='http://chat:8080/v1/')):
        with pytest.raises(ValueError):
            build_routes(config(aux))
    with pytest.raises(ValueError):
        build_routes(config(ocr(), ocr()))


@pytest.mark.parametrize('field,value', [
    ('max_inflight', 0), ('max_queue', -1), ('per_app_inflight', True),
    ('max_body_bytes', 0), ('queue_timeout', float('nan')), ('request_timeout', float('inf')),
    ('max_output_tokens', 8192), ('max_images', 2), ('embedding_dimensions', 0),
    ('aliases', ('ocr', 'ocr')), ('aliases', ('',)), ('aliases', (' ocr',)), ('aliases', ('ocr\nheader',)),
    ('backend_url', 'http://user:password@ocr/v1'), ('backend_url', 'http://ocr/v1?key=x'),
    ('backend_url', 'http://ocr/v1#secret'), ('backend_url', 'http://ocr/api/generate'),
    ('backend_url', 'file:///tmp/model'), ('backend_model', ''),
    ('name', 'arbitrary'), ('operation', 'embeddings'),
])
def test_invalid_route_configuration_fails_at_startup(field, value):
    with pytest.raises(ValueError):
        replace(ocr(), **{field: value})


def test_auxiliary_routes_are_opt_in_and_require_complete_config(monkeypatch):
    for key in ('OCR_ENABLED', 'EMBEDDINGS_ENABLED', 'OCR_BACKEND_URL', 'OCR_BACKEND_MODEL'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('OCR_MAX_INFLIGHT', 'stale-invalid-unused-setting')
    assert load_auxiliary_routes() == ()
    monkeypatch.setenv('OCR_ENABLED', 'typo')
    with pytest.raises(ValueError):
        load_auxiliary_routes()
    monkeypatch.setenv('OCR_ENABLED', 'true')
    monkeypatch.delenv('OCR_MAX_INFLIGHT')
    with pytest.raises(ValueError):
        load_auxiliary_routes()
    monkeypatch.setenv('OCR_BACKEND_URL', 'http://ocr:8080/v1')
    monkeypatch.setenv('OCR_BACKEND_MODEL', 'glm-ocr')
    routes = load_auxiliary_routes()
    assert len(routes) == 1 and routes[0].name == 'ocr'
    assert routes[0].max_inflight == routes[0].per_app_inflight == 1
