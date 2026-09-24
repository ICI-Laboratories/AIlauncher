"""Explicit llama.cpp backend inventory for the shared HTTP gateway.

This module configures routing and budgets only. It never starts an engine or
loads a model. Disabled auxiliary routes are absent from the public catalog.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from typing import Literal

from fastapi import HTTPException
import httpx


@dataclass(frozen=True)
class BackendRoute:
    name: str
    operation: Literal['chat', 'embeddings']
    backend_url: str
    backend_model: str
    aliases: tuple[str, ...]
    max_inflight: int = 1
    max_queue: int = 8
    per_app_inflight: int = 1
    queue_timeout: float = 30
    request_timeout: float = 120
    max_output_tokens: int = 4096
    max_body_bytes: int = 16 * 1024 * 1024
    max_context_tokens: int = 8192
    max_batch_size: int = 16
    max_input_chars: int = 8192
    max_total_input_chars: int = 65536
    embedding_dimensions: int = 1024
    max_images: int = 1
    max_image_bytes: int = 8 * 1024 * 1024
    max_image_side: int = 2048

    def __post_init__(self):
        if self.name not in {'chat', 'ocr', 'embeddings'}:
            raise ValueError('Unknown backend route category')
        expected = 'embeddings' if self.name == 'embeddings' else 'chat'
        if self.operation != expected:
            raise ValueError('Backend operation does not match its category')
        try:
            url = httpx.URL(self.backend_url)
        except (httpx.InvalidURL, ValueError) as exc:
            raise ValueError('Invalid backend URL') from exc
        if (url.scheme not in {'http', 'https'} or not url.host or url.userinfo
                or url.query or url.fragment or url.path.rstrip('/') != '/v1'):
            raise ValueError('Backend URL must be an HTTP(S) /v1 base without credentials or parameters')
        object.__setattr__(self, 'backend_url', str(url).rstrip('/'))
        if not isinstance(self.backend_model, str) or not self.backend_model.strip():
            raise ValueError('A backend model is required for every enabled route')
        if (not isinstance(self.aliases, tuple) or not self.aliases
                or any(not isinstance(alias, str) or not alias.strip()
                       or alias != alias.strip() or len(alias) > 128
                       or any(ord(char) < 32 or ord(char) == 127 for char in alias)
                       for alias in self.aliases)
                or len(set(self.aliases)) != len(self.aliases)):
            raise ValueError('Model aliases must be unique nonempty strings up to 128 characters')
        for name in ('max_inflight', 'per_app_inflight', 'max_output_tokens',
                     'max_body_bytes', 'max_context_tokens', 'max_batch_size',
                     'max_input_chars', 'max_total_input_chars', 'embedding_dimensions',
                     'max_images', 'max_image_bytes', 'max_image_side', 'max_queue'):
            value = getattr(self, name)
            minimum = 0 if name == 'max_queue' else 1
            if type(value) is not int or value < minimum:
                raise ValueError(f'{name} must be an integer >= {minimum}')
        for name in ('queue_timeout', 'request_timeout'):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if self.operation == 'chat' and self.max_output_tokens >= self.max_context_tokens:
            raise ValueError('Output budget must be smaller than context budget')
        if self.name == 'ocr' and self.max_images != 1:
            raise ValueError('OCR supports exactly one page image per request')


def _enabled(prefix: str) -> bool:
    value = os.getenv(f'{prefix}_ENABLED', 'false').strip().lower()
    if value not in {'true', 'false', '1', '0'}:
        raise ValueError(f'{prefix}_ENABLED must be true, false, 1 or 0')
    return value in {'true', '1'}


def load_auxiliary_routes() -> tuple[BackendRoute, ...]:
    routes = []
    for prefix, name, aliases in (('OCR', 'ocr', 'ocr'), ('EMBEDDINGS', 'embeddings', 'bge-m3')):
        if not _enabled(prefix):
            continue
        routes.append(BackendRoute(
            name=name,
            operation='chat' if name == 'ocr' else 'embeddings',
            backend_url=os.getenv(f'{prefix}_BACKEND_URL', '').strip(),
            backend_model=os.getenv(f'{prefix}_BACKEND_MODEL', '').strip(),
            aliases=tuple(x.strip() for x in os.getenv(f'{prefix}_MODEL_ALIASES', aliases).split(',')),
            max_inflight=int(os.getenv(f'{prefix}_MAX_INFLIGHT', '1')),
            max_queue=int(os.getenv(f'{prefix}_MAX_QUEUE', '8')),
            per_app_inflight=int(os.getenv(f'{prefix}_PER_APP_INFLIGHT', '1')),
            queue_timeout=float(os.getenv(f'{prefix}_QUEUE_TIMEOUT_SECONDS', '30')),
            request_timeout=float(os.getenv(f'{prefix}_REQUEST_TIMEOUT_SECONDS', '120')),
            max_output_tokens=int(os.getenv(f'{prefix}_MAX_OUTPUT_TOKENS', '4096')),
            max_body_bytes=int(os.getenv(f'{prefix}_MAX_BODY_BYTES', str(16 * 1024 * 1024 if name == 'ocr' else 1024 * 1024))),
            max_context_tokens=int(os.getenv(f'{prefix}_MAX_CONTEXT_TOKENS', '8192')),
            max_batch_size=int(os.getenv(f'{prefix}_MAX_BATCH_SIZE', '16')),
            max_input_chars=int(os.getenv(f'{prefix}_MAX_INPUT_CHARS', '8192')),
            max_total_input_chars=int(os.getenv(f'{prefix}_MAX_TOTAL_INPUT_CHARS', '65536')),
            embedding_dimensions=int(os.getenv(f'{prefix}_DIMENSIONS', '1024')),
            max_images=1,
            max_image_bytes=int(os.getenv(f'{prefix}_MAX_IMAGE_BYTES', str(8 * 1024 * 1024))),
            max_image_side=int(os.getenv(f'{prefix}_MAX_IMAGE_SIDE', '2048')),
        ))
    return tuple(routes)


def build_routes(cfg) -> dict[str, BackendRoute]:
    chat = BackendRoute(
        name='chat', operation='chat', backend_url=cfg.backend_url,
        backend_model=cfg.backend_model, aliases=cfg.aliases,
        max_inflight=cfg.max_inflight, max_queue=cfg.max_queue,
        per_app_inflight=cfg.per_app_inflight, queue_timeout=cfg.queue_timeout,
        request_timeout=cfg.request_timeout, max_output_tokens=cfg.max_output_tokens,
        max_body_bytes=cfg.max_body_bytes, max_context_tokens=cfg.max_context_tokens,
    )
    routes = {}
    used_aliases = set()
    used_backends = set()
    for route in (chat, *cfg.auxiliary_routes):
        if not isinstance(route, BackendRoute):
            raise ValueError('Auxiliary routes must be BackendRoute instances')
        if route.name in routes or used_aliases.intersection(route.aliases):
            raise ValueError('Route categories and model aliases cannot overlap')
        if route.backend_url in used_backends:
            raise ValueError('Routes require distinct backend URLs to keep admission limits independent')
        routes[route.name] = route
        used_aliases.update(route.aliases)
        used_backends.add(route.backend_url)
    return routes


def resolve_route(routes: dict[str, BackendRoute], model: str | None,
                  operation: str | None) -> tuple[BackendRoute, str]:
    if model is None:
        if operation == 'embeddings':
            raise HTTPException(422, 'An embedding model alias is required')
        model = routes['chat'].aliases[0]
    for route in routes.values():
        if model in route.aliases:
            if operation is not None and route.operation != operation:
                raise HTTPException(409, 'Model does not support this endpoint')
            return route, model
    raise HTTPException(404, 'Unknown or disabled model alias')
