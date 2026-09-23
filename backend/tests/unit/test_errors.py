from __future__ import annotations

import pytest

from cfi.core import errors


def test_problem_details_shape() -> None:
    body = errors.problem_details(
        status=502,
        title="Data provider error",
        detail="upstream failed",
        error_code="provider_error",
        request_id="abc",
        instance="/x",
    )
    assert body == {
        "type": "urn:cfi:error:provider_error",
        "title": "Data provider error",
        "status": 502,
        "detail": "upstream failed",
        "error_code": "provider_error",
        "instance": "/x",
        "request_id": "abc",
    }


@pytest.mark.parametrize(
    ("cls", "retryable"),
    [
        (errors.ProviderTransientError, True),
        (errors.ProviderPermanentError, False),
        (errors.SchemaMismatchError, False),
        (errors.ProviderNotConfiguredError, False),
        (errors.ServiceUnavailableError, True),
        (errors.ComputationError, False),
    ],
)
def test_retry_policy_is_explicit(cls: type[errors.CFIError], retryable: bool) -> None:
    assert cls.retryable is retryable


def test_error_codes_are_unique() -> None:
    classes = [
        c for c in vars(errors).values() if isinstance(c, type) and issubclass(c, errors.CFIError)
    ]
    codes = [c.error_code for c in classes]
    assert len(codes) == len(set(codes)), codes


def test_insufficient_data_uses_the_required_phrase() -> None:
    assert errors.InsufficientDataError.title == "Insufficient data."


def test_context_is_preserved() -> None:
    err = errors.ProviderTransientError("timeout", provider_id="x")
    assert err.detail == "timeout"
    assert err.context == {"provider_id": "x"}
