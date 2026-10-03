"""Anthropic Claude API client (Phase 21 spec, Section 10; ADR-0068).

Reuses ``cfi.providers.http.ProviderHttpClient`` — the same authentication, timeout, retry with
exponential backoff, token-bucket rate limiting, circuit breaking, and per-attempt request logging
every ingestion provider already gets (R8, R13) — rather than a bespoke HTTP client. The Messages
API needs a JSON POST body, which ``RequestSpec`` did not carry before this phase; the two small,
additive fields it gained (``json_body``, ``headers``) close that gap without changing behavior for
any existing GET-only adapter (both default to ``None``/empty, see ADR-0068).

``ProviderHttpClient.send()`` already classifies and retries timeouts, connection errors, 429s
(honouring ``Retry-After``) and 5xx server errors, and raises ``ProviderPermanentError`` for 4xx and
missing credentials — Section 10's "timeout handling, retry behavior, rate-limit handling" are
therefore inherited, not reimplemented. This module adds only what is specific to the Messages API
itself: building the request body, and parsing/validating the 2xx JSON response shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from cfi.core.config import Settings
from cfi.core.errors import AIValidationError
from cfi.domain.enums import AuthType
from cfi.providers.base import AuthSpec, ProviderCapabilities, RateLimitSpec, RequestSpec
from cfi.providers.http import ProviderHttpClient

ANTHROPIC_PROVIDER_ID = "anthropic"
MESSAGES_PATH = "/v1/messages"


def anthropic_capabilities(settings: Settings) -> ProviderCapabilities:
    return ProviderCapabilities(
        provider_id=ANTHROPIC_PROVIDER_ID,
        display_name="Anthropic Claude API",
        base_url=settings.anthropic_api_base_url,
        datasets=frozenset(),  # not a dataset-ingestion provider — analyst calls only
        auth=AuthSpec(
            type=AuthType.API_KEY_HEADER,
            name="x-api-key",
            env_var="CFI_ANTHROPIC_API_KEY",
        ),
        rate_limit=RateLimitSpec(
            requests=settings.anthropic_rate_limit_requests,
            per_seconds=settings.anthropic_rate_limit_per_seconds,
        ),
        timeout_seconds=settings.anthropic_timeout_seconds,
        max_pages=1,
        original_source="Anthropic",
        terms_verified=True,
        notes="Messages API (POST /v1/messages); JSON request/response body, not query parameters.",
    )


@dataclass(frozen=True, slots=True)
class ClaudeResponse:
    text: str
    stop_reason: str
    model: str
    input_tokens: int
    output_tokens: int


class ClaudeClient:
    """Thin wrapper: build one Messages API request, send it through ``ProviderHttpClient``, parse
    the response. One call = one attempt sequence (retries are ``ProviderHttpClient``'s own)."""

    def __init__(self, http: ProviderHttpClient, *, model: str, max_tokens: int) -> None:
        self._http = http
        self.model = model
        self.max_tokens = max_tokens

    async def complete(self, *, system: str, user: str) -> ClaudeResponse:
        spec = RequestSpec(
            path=MESSAGES_PATH,
            method="POST",
            headers={
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json_body={
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        raw = await self._http.send(spec)
        try:
            payload: dict[str, Any] = json.loads(raw.body)
        except json.JSONDecodeError as exc:
            raise AIValidationError(
                "Claude API returned a non-JSON response body.", provider_id=ANTHROPIC_PROVIDER_ID
            ) from exc
        try:
            content = payload["content"]
            text = "".join(
                block.get("text", "") for block in content if block.get("type") == "text"
            )
            usage = payload.get("usage", {})
            return ClaudeResponse(
                text=text,
                stop_reason=payload.get("stop_reason") or "unknown",
                model=payload.get("model") or self.model,
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AIValidationError(
                "Claude API response is missing an expected field "
                "('content'/'usage' shape unexpected).",
                provider_id=ANTHROPIC_PROVIDER_ID,
            ) from exc


def parse_json_response(text: str) -> dict[str, Any]:
    """Parse Claude's own response text as the required single JSON object (Section 11: reject
    malformed output explicitly, never silently reinterpret it). Strips a markdown code fence if
    Claude added one despite being told not to — a tolerant parse, not a silent reinterpretation of
    the *content*, only of harmless wrapping."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise AIValidationError(
            f"Claude's response text is not valid JSON: {exc}.", provider_id=ANTHROPIC_PROVIDER_ID
        ) from exc
    if not isinstance(parsed, dict):
        raise AIValidationError(
            "Claude's response JSON is not an object.", provider_id=ANTHROPIC_PROVIDER_ID
        )
    return parsed
