"""Bound auxiliary requests and validate untrusted inference responses.

Image validation reads only standard image headers; decoding remains the OCR
engine's responsibility. None of the errors include client or model content.
"""
from __future__ import annotations

import base64
import binascii
import math
import struct
from typing import Any, Literal
import zlib

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class EmbeddingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: StrictStr = Field(min_length=1)
    input: StrictStr | list[StrictStr]
    encoding_format: Literal["float"] = "float"
    dimensions: int | None = Field(default=None, strict=True, gt=0)

    @field_validator("model")
    @classmethod
    def model_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A model alias is required")
        return value


def _invalid_image() -> HTTPException:
    return HTTPException(422, "OCR requires a valid inline PNG or JPEG image")


def _png_dimensions(data: bytes) -> tuple[int, int]:
    if (len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n"
            or data[8:16] != b"\x00\x00\x00\rIHDR"):
        raise _invalid_image()
    if zlib.crc32(data[12:29]) != int.from_bytes(data[29:33], "big"):
        raise _invalid_image()
    return struct.unpack(">II", data[16:24])


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"\xff\xd8"):
        raise _invalid_image()
    cursor = 2
    # SOF markers carrying dimensions; exclude DHT, JPG and DAC markers.
    frame_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                     0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while cursor < len(data):
        if data[cursor] != 0xFF:
            raise _invalid_image()
        while cursor < len(data) and data[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(data):
            raise _invalid_image()
        marker = data[cursor]
        cursor += 1
        if marker in {0x00, 0xD8, 0xD9, 0xDA}:
            # A frame header must precede scan data and end-of-image.
            raise _invalid_image()
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if cursor + 2 > len(data):
            raise _invalid_image()
        length = int.from_bytes(data[cursor:cursor + 2], "big")
        if length < 2 or cursor + length > len(data):
            raise _invalid_image()
        if marker in frame_markers:
            if length < 8:
                raise _invalid_image()
            components = data[cursor + 7]
            if components not in {1, 3, 4} or length != 8 + 3 * components:
                raise _invalid_image()
            height, width = struct.unpack(">HH", data[cursor + 3:cursor + 7])
            return width, height
        cursor += length
    raise _invalid_image()


def _validate_image_url(value: Any, route: Any) -> None:
    if (not isinstance(value, dict) or set(value) - {"url", "detail"}
            or not isinstance(value.get("url"), str)
            or ("detail" in value and (not isinstance(value["detail"], str)
                                      or value["detail"] not in {"auto", "low", "high"}))):
        raise _invalid_image()
    url = value["url"]
    header, separator, encoded = url.partition(",")
    if not separator or header not in {
        "data:image/png;base64", "data:image/jpeg;base64", "data:image/jpg;base64",
    }:
        raise _invalid_image()
    if len(encoded) > 4 * ((route.max_image_bytes + 2) // 3):
        raise HTTPException(413, "OCR image exceeds the configured byte limit")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise _invalid_image() from exc
    if len(raw) > route.max_image_bytes:
        raise HTTPException(413, "OCR image exceeds the configured byte limit")
    width, height = (_png_dimensions(raw) if header == "data:image/png;base64"
                     else _jpeg_dimensions(raw))
    if width <= 0 or height <= 0:
        raise _invalid_image()
    if max(width, height) > route.max_image_side:
        raise HTTPException(413, "OCR image exceeds the configured dimension limit")


def validate_ocr_messages(messages: Any, route: Any) -> None:
    """Validate a bounded, inline-only OCR conversation without modifying it."""
    invalid = "Unsupported OCR message or content structure"
    if not isinstance(messages, list) or not messages:
        raise HTTPException(422, invalid)
    images = 0
    text_sizes = []
    for message in messages:
        if (not isinstance(message, dict) or set(message) - {"role", "content", "name"}
                or not isinstance(message.get("role"), str)
                or message["role"] not in {"system", "developer", "user", "assistant"}
                or ("name" in message and not isinstance(message["name"], str))):
            raise HTTPException(422, invalid)
        content = message.get("content")
        if isinstance(content, str):
            text_sizes.append(len(content))
            continue
        if not isinstance(content, list) or not content:
            raise HTTPException(422, invalid)
        for part in content:
            if not isinstance(part, dict):
                raise HTTPException(422, invalid)
            if part.get("type") == "text":
                if set(part) != {"type", "text"} or not isinstance(part["text"], str):
                    raise HTTPException(422, invalid)
                text_sizes.append(len(part["text"]))
            elif part.get("type") == "image_url":
                if set(part) != {"type", "image_url"}:
                    raise HTTPException(422, invalid)
                images += 1
                if images > route.max_images:
                    raise HTTPException(422, "OCR image count exceeds the configured limit")
                _validate_image_url(part["image_url"], route)
            else:
                raise HTTPException(422, invalid)
    if images == 0:
        raise HTTPException(422, "OCR requires an inline image")
    if (any(size > route.max_input_chars for size in text_sizes)
            or sum(text_sizes) > route.max_total_input_chars):
        raise HTTPException(413, "OCR text exceeds the configured input limit")


def prepare_embeddings(payload: EmbeddingPayload, route: Any) -> dict[str, Any]:
    """Validate text budgets and build a request using the private backend model."""
    inputs = payload.input if isinstance(payload.input, list) else [payload.input]
    if not inputs or len(inputs) > route.max_batch_size:
        raise HTTPException(422, "Embedding input count exceeds the configured limits")
    if any(not item.strip() for item in inputs):
        raise HTTPException(422, "Embedding inputs must contain text")
    if (any(len(item) > route.max_input_chars for item in inputs)
            or sum(map(len, inputs)) > route.max_total_input_chars):
        raise HTTPException(413, "Embedding text exceeds the configured input limit")
    if payload.dimensions is not None and payload.dimensions != route.embedding_dimensions:
        raise HTTPException(422, "Embedding dimensions do not match the configured model")
    body = {"model": route.backend_model, "input": payload.input, "encoding_format": "float"}
    # Fixed-width models do not need a dimensions parameter at the llama.cpp
    # endpoint. The public parameter is an assertion, validated above.
    return body


def validate_embeddings_response(data: Any, route: Any, count: int, alias: str) -> dict[str, Any]:
    """Return only indexed, finite fixed-width vectors and numeric token usage."""
    invalid = HTTPException(502, "Embedding backend returned an invalid response")
    if not isinstance(data, dict) or not isinstance(data.get("data"), list) or len(data["data"]) != count:
        raise invalid
    ordered = {}
    for item in data["data"]:
        if not isinstance(item, dict):
            raise invalid
        index = item.get("index")
        vector = item.get("embedding")
        if (type(index) is not int or not 0 <= index < count or index in ordered
                or not isinstance(vector, list) or len(vector) != route.embedding_dimensions):
            raise invalid
        nonzero = False
        for value in vector:
            if type(value) not in {int, float}:
                raise invalid
            try:
                if not math.isfinite(value):
                    raise invalid
            except OverflowError as exc:
                raise invalid from exc
            nonzero |= value != 0
        if not nonzero:
            raise invalid
        ordered[index] = {"object": "embedding", "index": index, "embedding": vector}
    result = {"object": "list", "data": [ordered[i] for i in range(count)], "model": alias}
    usage = data.get("usage")
    if isinstance(usage, dict):
        safe_usage = {key: usage[key] for key in ("prompt_tokens", "total_tokens")
                      if type(usage.get(key)) is int and usage[key] >= 0}
        if safe_usage:
            result["usage"] = safe_usage
    return result
