"""The Anthropic Messages API client (Phase 21, Section 10): request shape, response parsing,
malformed-response handling, and that timeout/retry/rate-limit behavior is genuinely inherited from
``ProviderHttpClient`` rather than reimplemented. A fake in-process transport stands in for the
real API — no network access, matching every other provider's own test convention.
"""

from __future__ import annotations

import json

import httpx2
import pytest

from cfi.analyst.client import ClaudeClient, anthropic_capabilities, parse_json_response
from cfi.core.config import Settings
from cfi.core.errors import AIValidationError, ProviderPermanentError, ProviderTransientError
from cfi.providers.http import ListRecorder, ProviderHttpClient, RetryPolicy
from tests.support import FakeClock

NO_JITTER = RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=1, jitter=0)


def _success_body(text: str = "hello") -> bytes:
    return json.dumps(
        {
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "model": "claude-sonnet-5",
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }
    ).encode()


def _client(
    handler: httpx2.MockTransport, settings: Settings, *, retry: RetryPolicy = NO_JITTER
) -> tuple[ClaudeClient, ListRecorder]:
    recorder = ListRecorder()
    clock = FakeClock()
    http = ProviderHttpClient(
        anthropic_capabilities(settings),
        transport=handler,
        retry=retry,
        recorder=recorder,
        environ={"CFI_ANTHROPIC_API_KEY": "test-key"},
        sleep=clock.sleep,
        clock=clock,
    )
    return ClaudeClient(http, model=settings.anthropic_model, max_tokens=4096), recorder


async def test_complete_sends_post_with_json_body_and_auth_header(settings: Settings) -> None:
    captured: list[httpx2.Request] = []

    async def handle(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(
            200, content=_success_body(), headers={"content-type": "application/json"}
        )

    client, _recorder = _client(httpx2.MockTransport(handle), settings)
    response = await client.complete(system="You are an analyst.", user="Analyze this.")

    assert response.text == "hello"
    assert response.input_tokens == 100
    assert response.output_tokens == 20
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert req.url.path == "/v1/messages"
    assert req.headers["x-api-key"] == "test-key"
    assert req.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(req.content)
    assert body["system"] == "You are an analyst."
    assert body["messages"] == [{"role": "user", "content": "Analyze this."}]
    await client._http.aclose()


async def test_complete_raises_ai_validation_error_on_non_json_body(settings: Settings) -> None:
    async def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"not json", headers={"content-type": "text/plain"})

    client, _recorder = _client(httpx2.MockTransport(handle), settings)
    with pytest.raises(AIValidationError):
        await client.complete(system="s", user="u")
    await client._http.aclose()


async def test_complete_raises_ai_validation_error_on_missing_content_field(
    settings: Settings,
) -> None:
    async def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=json.dumps({"stop_reason": "end_turn"}).encode(),
            headers={"content-type": "application/json"},
        )

    client, _recorder = _client(httpx2.MockTransport(handle), settings)
    with pytest.raises(AIValidationError):
        await client.complete(system="s", user="u")
    await client._http.aclose()


async def test_timeout_is_retried_then_raises_provider_transient_error(settings: Settings) -> None:
    calls = {"n": 0}

    async def handle(_request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        raise httpx2.ReadTimeout("mock timeout", request=_request)

    client, recorder = _client(httpx2.MockTransport(handle), settings)
    with pytest.raises(ProviderTransientError):
        await client.complete(system="s", user="u")
    assert calls["n"] == NO_JITTER.max_attempts
    assert [a.outcome for a in recorder.attempts] == ["timeout"] * NO_JITTER.max_attempts
    await client._http.aclose()


async def test_rate_limit_429_is_retried_honouring_retry_after(settings: Settings) -> None:
    attempts = {"n": 0}

    async def handle(_request: httpx2.Request) -> httpx2.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx2.Response(429, headers={"retry-after": "0"}, content=b"{}")
        return httpx2.Response(
            200, content=_success_body(), headers={"content-type": "application/json"}
        )

    client, recorder = _client(httpx2.MockTransport(handle), settings)
    response = await client.complete(system="s", user="u")
    assert response.text == "hello"
    assert [a.outcome for a in recorder.attempts] == ["rate_limited", "success"]
    await client._http.aclose()


async def test_missing_credential_raises_provider_permanent_error(settings: Settings) -> None:
    async def handle(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, content=_success_body(), headers={"content-type": "application/json"}
        )

    recorder = ListRecorder()
    clock = FakeClock()
    http = ProviderHttpClient(
        anthropic_capabilities(settings),
        transport=httpx2.MockTransport(handle),
        retry=NO_JITTER,
        recorder=recorder,
        environ={},  # no CFI_ANTHROPIC_API_KEY
        sleep=clock.sleep,
        clock=clock,
    )
    client = ClaudeClient(http, model=settings.anthropic_model, max_tokens=4096)
    with pytest.raises(ProviderPermanentError):
        await client.complete(system="s", user="u")
    await http.aclose()


def test_parse_json_response_accepts_plain_json() -> None:
    parsed = parse_json_response('{"summary": "ok"}')
    assert parsed == {"summary": "ok"}


def test_parse_json_response_strips_markdown_code_fence() -> None:
    parsed = parse_json_response('```json\n{"summary": "ok"}\n```')
    assert parsed == {"summary": "ok"}


def test_parse_json_response_rejects_invalid_json() -> None:
    with pytest.raises(AIValidationError):
        parse_json_response("not json at all")


def test_parse_json_response_rejects_a_json_array() -> None:
    with pytest.raises(AIValidationError):
        parse_json_response("[1, 2, 3]")
