import json

from lmserv.config import Config
from lmserv.gateway.models import ModelCapabilities, ModelRoute, RoutedChatResult, RuntimeChatResult
from lmserv.server.audit import RequestAuditLogger


def _sample_routed_result() -> RoutedChatResult:
    main_route = ModelRoute(
        name="sara-main",
        backend="ollama",
        target="gemma4:26b",
        capabilities=ModelCapabilities(),
    )
    selected_route = ModelRoute(
        name="sara-structured",
        backend="ollama",
        target="qwen3:30b",
        capabilities=ModelCapabilities(structured_output=True, json_mode=True, tools=True),
    )
    return RoutedChatResult(
        requested_model="sara-main",
        primary_route=main_route,
        selected_route=selected_route,
        routing_reason="Ruta automatica hacia 'sara-structured'.",
        result=RuntimeChatResult(
            content='{"answer":"ok"}',
            usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        ),
    )


def test_request_audit_writes_metadata_without_content(tmp_path):
    cfg = Config(
        model="dummy",
        backend="ollama",
        api_key="test-key",
        request_log_path=str(tmp_path / "requests.jsonl"),
        request_log_include_content=False,
    )
    audit = RequestAuditLogger(cfg)

    audit.log_chat_event(
        endpoint="/v1/chat/completions",
        client_ip="127.0.0.1",
        user_agent="pytest",
        correlation_id="corr-1",
        idempotency_key="idem-1",
        requested_model="sara-main",
        messages=[{"role": "user", "content": "Hola mundo"}],
        response_format={"type": "json_object"},
        tools=[],
        stream_requested=False,
        routed_result=_sample_routed_result(),
        response_payload={"id": "chatcmpl-test"},
        latency_ms=12.5,
    )

    payload = json.loads((tmp_path / "requests.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert payload["selected_model"] == "sara-structured"
    assert payload["request"]["messages"]["items"][0]["chars"] == 10
    assert "content" not in payload["request"]["messages"]["items"][0]


def test_request_audit_truncates_content_when_enabled(tmp_path):
    cfg = Config(
        model="dummy",
        backend="ollama",
        api_key="test-key",
        request_log_path=str(tmp_path / "requests.jsonl"),
        request_log_include_content=True,
        request_log_max_chars=8,
    )
    audit = RequestAuditLogger(cfg)

    audit.log_chat_event(
        endpoint="/chat",
        client_ip=None,
        user_agent=None,
        correlation_id=None,
        idempotency_key=None,
        requested_model=None,
        messages=[{"role": "user", "content": "123456789ABC"}],
        response_format=None,
        tools=None,
        stream_requested=False,
        routed_result=_sample_routed_result(),
        response_payload=None,
        latency_ms=3.0,
    )

    payload = json.loads((tmp_path / "requests.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert payload["request"]["messages"]["items"][0]["content"].startswith("12345678")
    assert "[truncated" in payload["request"]["messages"]["items"][0]["content"]
    assert payload["response"]["content"].startswith('{"answer')
