"""Boundaries for auxiliary model inputs and untrusted model responses."""
import base64
from copy import deepcopy
import math
import struct
from types import SimpleNamespace
import zlib

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from lmserv.server.auxiliary_payloads import (
    EmbeddingPayload, prepare_embeddings, validate_embeddings_response, validate_ocr_messages,
)


def route(**overrides):
    return SimpleNamespace(**{
        "backend_model": "private-model", "max_images": 1,
        "max_image_bytes": 8 * 1024 * 1024, "max_image_side": 2048,
        "embedding_dimensions": 1024, "max_batch_size": 16,
        "max_input_chars": 8192, "max_total_input_chars": 65536, **overrides,
    })


def png_header(width=1, height=1):
    header = b"IHDR" + struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + header + struct.pack(">I", zlib.crc32(header))


def jpeg_header(width=1, height=1, marker=0xC0):
    return (b"\xff\xd8\xff\xe0\x00\x04JF" + bytes([0xFF, marker])
            + struct.pack(">HBHHB", 17, 8, height, width, 3)
            + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00" + b"\xff\xd9")


def image_part(data=None, mime="png"):
    data = png_header() if data is None else data
    return {"type": "image_url", "image_url": {
        "url": f"data:image/{mime};base64," + base64.b64encode(data).decode(), "detail": "auto",
    }}


def messages(part=None):
    return [{"role": "system", "content": "Transcribe exactly."},
            {"role": "user", "name": "reader", "content": [
                {"type": "text", "text": "Preserve accents: café."},
                image_part() if part is None else part,
            ]}]


@pytest.mark.parametrize("part", [
    image_part(), image_part(jpeg_header(), "jpeg"), image_part(jpeg_header(marker=0xC2), "jpg"),
    image_part(png_header(2048, 2048)), image_part(jpeg_header(2048, 2048), "jpeg"),
])
def test_ocr_accepts_bounded_inline_headers_without_mutating_messages(part):
    payload = messages(part)
    original = deepcopy(payload)
    validate_ocr_messages(payload, route())
    assert payload == original


@pytest.mark.parametrize("part", [
    {"type": "image_url", "image_url": {"url": "https://host/private.png"}},
    {"type": "image_url", "image_url": {"url": "file:///private.png"}},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,%%%"}},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,ñ"}},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,"}},
    image_part(b"GIF89a", "gif"), image_part(jpeg_header(), "png"), image_part(png_header(), "jpeg"),
    image_part(png_header()[:25]), image_part(png_header()[:-1] + b"\0"),
    image_part(png_header(0, 1)), image_part(jpeg_header(1, 0), "jpeg"),
    image_part(b"\xff\xd8\xff\xe0\x00\x10abc", "jpeg"),
    image_part(b"\xff\xd8\xff\xda\x00\x02", "jpeg"),
    image_part(b"\xff\xd8\xff\xc0\x00\x02", "jpeg"),
])
def test_ocr_rejects_external_mislabeled_corrupt_and_empty_images(part):
    with pytest.raises(HTTPException) as error:
        validate_ocr_messages(messages(part), route())
    assert error.value.status_code == 422
    assert "private" not in error.value.detail


@pytest.mark.parametrize("payload", [
    None, [], [None], [{"role": [], "content": "secret"}],
    [{"role": "tool", "content": "secret"}],
    [{"role": "user", "content": {"image_url": "secret"}}],
    [{"role": "user", "content": []}],
    [{"role": "user", "content": None}],
    [{"role": "user", "content": "secret"}],
    messages() + [{"role": "user", "content": "secret", "images": ["hidden"]}],
    messages({"type": "text", "text": "secret", "image_url": {"url": "hidden"}}),
    messages({"type": "input_audio", "input_audio": {"data": "secret"}}),
    messages({"type": "image_url", "image_url": "secret"}),
    messages({"type": "image_url", "image_url": {"url": "secret", "detail": {}}}),
    messages({"type": "image_url", "image_url": {"url": "secret", "extra": "secret"}}),
    messages({"type": [], "image_url": "secret"}),
])
def test_ocr_rejects_unsupported_and_hidden_modalities(payload):
    with pytest.raises(HTTPException) as error:
        validate_ocr_messages(payload, route())
    assert error.value.status_code == 422
    assert "secret" not in error.value.detail


def test_ocr_counts_images_across_all_messages():
    payload = messages() + [{"role": "assistant", "content": [image_part()]}]
    with pytest.raises(HTTPException) as error:
        validate_ocr_messages(payload, route())
    assert error.value.status_code == 422


@pytest.mark.parametrize("part,limits", [
    (image_part(png_header(2049, 1)), {}),
    (image_part(png_header(1, 2**32 - 1)), {}),
    (image_part(jpeg_header(1, 2049), "jpeg"), {}),
    (image_part(), {"max_image_bytes": 32}),
    (image_part(png_header() + b"x" * 200), {"max_image_bytes": 32}),
])
def test_ocr_rejects_oversize_dimensions_and_encoded_or_decoded_bytes(part, limits):
    with pytest.raises(HTTPException) as error:
        validate_ocr_messages(messages(part), route(**limits))
    assert error.value.status_code == 413


@pytest.mark.parametrize("limits", [{"max_input_chars": 8}, {"max_total_input_chars": 8}])
def test_ocr_bounds_instruction_text(limits):
    with pytest.raises(HTTPException) as error:
        validate_ocr_messages(messages(), route(**limits))
    assert error.value.status_code == 413


@pytest.mark.parametrize("extra", [
    {"model": ""}, {"model": "  "}, {"model": 123}, {"model": None},
    {"input": [1, 2]}, {"input": [[1, 2]]}, {"input": True}, {"input": None},
    {"input": ["text", 1]}, {"encoding_format": "base64"},
    {"dimensions": True}, {"dimensions": "1024"}, {"dimensions": 1024.0}, {"dimensions": 0},
    {"backend_url": "http://private"}, {"user": "private"},
])
def test_embedding_schema_rejects_token_arrays_coercion_and_backend_controls(extra):
    with pytest.raises(ValidationError):
        EmbeddingPayload.model_validate({"model": "bge-m3", "input": "text", **extra})


@pytest.mark.parametrize("data", [{"input": "text"}, {"model": "bge-m3"}])
def test_embedding_model_and_input_are_required(data):
    with pytest.raises(ValidationError):
        EmbeddingPayload.model_validate(data)


@pytest.mark.parametrize("value", ["café", ["  café  ", "libro"], ["x"] * 16])
def test_embedding_request_preserves_text_and_substitutes_private_model(value):
    payload = EmbeddingPayload(model="bge-m3", input=value, dimensions=1024)
    assert prepare_embeddings(payload, route()) == {
        "model": "private-model", "input": value, "encoding_format": "float",
    }


@pytest.mark.parametrize("value,status,limits", [
    ([], 422, {}), ("", 422, {}), (" \n\t", 422, {}), (["valid", " "], 422, {}),
    (["x"] * 17, 422, {}), ("x" * 8193, 413, {}),
    (["x" * 8192] * 9, 413, {}), (["123", "123"], 413, {"max_total_input_chars": 5}),
])
def test_embedding_input_budgets(value, status, limits):
    with pytest.raises(HTTPException) as error:
        prepare_embeddings(EmbeddingPayload(model="bge-m3", input=value), route(**limits))
    assert error.value.status_code == status


def test_embedding_dimension_assertion_is_exact():
    with pytest.raises(HTTPException) as error:
        prepare_embeddings(EmbeddingPayload(model="bge-m3", input="text", dimensions=512), route())
    assert error.value.status_code == 422


def response(vectors=None):
    vectors = [[1.0] + [0.0] * 1023] if vectors is None else vectors
    return {"model": "secret-backend", "data": [
        {"object": "embedding", "index": index, "embedding": vector}
        for index, vector in enumerate(vectors)
    ], "usage": {"prompt_tokens": 3, "total_tokens": 3}}


def test_embedding_response_sorts_indexes_replaces_model_and_drops_unknown_fields():
    raw = response([[1] + [0] * 1023, [0, -1] + [0] * 1022])
    raw["data"].reverse()
    raw["data"][0]["prompt"] = "secret"
    raw["usage"]["private"] = "secret"
    raw["private"] = "secret"
    result = validate_embeddings_response(raw, route(), 2, "bge-m3")
    assert [item["index"] for item in result["data"]] == [0, 1]
    assert result["model"] == "bge-m3"
    assert result["object"] == "list"
    assert result["usage"] == {"prompt_tokens": 3, "total_tokens": 3}
    assert "secret" not in str(result)


@pytest.mark.parametrize("vector", [
    [0.0] * 1024, [1.0] * 1023, [1.0] * 1025,
    [math.nan] + [0] * 1023, [math.inf] + [0] * 1023, [-math.inf] + [0] * 1023,
    [True] + [0] * 1023, ["secret"] + [0] * 1023, [None] + [0] * 1023,
    [10**1000] + [0] * 1023, {"private": "secret"}, "secret",
])
def test_embedding_response_rejects_invalid_vectors(vector):
    with pytest.raises(HTTPException) as error:
        validate_embeddings_response(response([vector]), route(), 1, "bge-m3")
    assert error.value.status_code == 502
    assert "secret" not in error.value.detail


@pytest.mark.parametrize("data", [
    None, [], {}, {"data": "secret"}, {"data": []}, {"data": [None]},
    {"data": [{"index": True, "embedding": [1] * 1024}]},
    {"data": [{"index": "0", "embedding": [1] * 1024}]},
    {"data": [{"index": -1, "embedding": [1] * 1024}]},
    {"data": [{"index": 1, "embedding": [1] * 1024}]},
])
def test_embedding_response_rejects_invalid_schema_count_and_indexes(data):
    with pytest.raises(HTTPException) as error:
        validate_embeddings_response(data, route(), 1, "bge-m3")
    assert error.value.status_code == 502


def test_embedding_response_rejects_duplicate_indexes():
    raw = response([[1] * 1024, [2] * 1024])
    raw["data"][1]["index"] = 0
    with pytest.raises(HTTPException) as error:
        validate_embeddings_response(raw, route(), 2, "bge-m3")
    assert error.value.status_code == 502


@pytest.mark.parametrize("usage,expected", [
    ({"prompt_tokens": -1, "total_tokens": "secret"}, None),
    ({"prompt_tokens": True, "total_tokens": 2.5}, None),
    ({"prompt_tokens": 0, "total_tokens": 3, "extra": "secret"}, {"prompt_tokens": 0, "total_tokens": 3}),
    ({"prompt_tokens": 3, "total_tokens": None}, {"prompt_tokens": 3}),
    ("secret", None), (None, None),
])
def test_embedding_response_keeps_only_nonnegative_integer_usage(usage, expected):
    raw = response()
    raw["usage"] = usage
    result = validate_embeddings_response(raw, route(), 1, "bge-m3")
    assert result.get("usage") == expected
