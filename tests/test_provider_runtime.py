from __future__ import annotations

import pytest

from study_runtime import providers


def test_openai_responses_payload_preserves_exact_effort(monkeypatch):
    seen = []

    def fake_http(url, headers, payload, timeout):
        seen.append((url, payload))
        return 200, {
            "model": "gpt-5.6-sol-2026-09-01",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 2},
        }

    monkeypatch.setattr(providers, "_http_json", fake_http)
    text, status, meta = providers.call_provider(
        "openai", "gpt-5.6-sol", "sys", "user", {"OPENAI_API_KEY": "x"},
        reasoning_effort="medium", max_attempts=1, sleep_fn=lambda _: None,
    )
    assert status == "ok"
    assert text == "ok"
    assert seen[0][0].endswith("/v1/responses")
    assert seen[0][1]["reasoning"] == {"effort": "medium"}
    assert meta["resolved_model"] == "gpt-5.6-sol-2026-09-01"
    assert meta["request_sha256"]


def test_retryable_provider_failure_is_retried(monkeypatch):
    calls = {"n": 0}

    def fake_http(url, headers, payload, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return 429, {"error": {"message": "rate"}}
        return 200, {
            "model": "grok-4.6",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "answer"}]}],
            "usage": {},
        }

    monkeypatch.setattr(providers, "_http_json", fake_http)
    text, status, meta = providers.call_provider(
        "xai", "grok-4.6", "sys", "user", {"XAI_API_KEY": "x"},
        reasoning_effort="medium", max_attempts=2, retry_backoff_seconds=0,
        sleep_fn=lambda _: None,
    )
    assert status == "ok"
    assert text == "answer"
    assert meta["attempts"] == 2


def test_transport_failure_is_not_model_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise providers.TransportError("timeout")

    monkeypatch.setattr(providers, "_http_json", fail)
    text, status, meta = providers.call_provider(
        "anthropic", "claude-opus-5", "sys", "user", {"ANTHROPIC_API_KEY": "x"},
        reasoning_effort="high", max_attempts=2, retry_backoff_seconds=0,
        sleep_fn=lambda _: None,
    )
    assert text == ""
    assert status == "transport_failure"
    assert meta["error_type"] == "transport_failure"
    assert meta["attempts"] == 2


def test_google_explicit_thinking_level_is_frozen():
    _, _, payload, _ = providers._request_for_provider(
        "google", "gemini-3.1-pro-preview", "sys", "user", "x", "high", 100
    )
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "high"}


def test_google_xhigh_fails_closed():
    with pytest.raises(ValueError):
        providers._request_for_provider(
            "google", "gemini-3.1-pro-preview", "sys", "user", "x", "xhigh", 100
        )
