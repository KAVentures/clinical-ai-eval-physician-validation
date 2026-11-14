"""Provider calls with frozen provenance, exact effort settings and bounded retry.

This module deliberately distinguishes:
- transport_failure: timeout/network failure after retries;
- provider_failure: HTTP/API failure after retries;
- model_output_failure: successful API response with no usable model text;
- ok: successful API response with non-empty model text.

No failure is silently converted into a clinical model answer.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KEY_NAMES = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
}
RETRYABLE_HTTP = {408, 409, 425, 429, 500, 502, 503, 504}
EFFORTS = {"provider_default", "low", "medium", "high", "xhigh"}

# Rehearsal only. When this variable is "1" no network request is made: a local
# simulator answers in each provider's real response shape, so request building,
# parsing, retry and failure classification all run for real. Every record it
# produces is marked (simulated=true, endpoint simulated://...) and preflight,
# the study lock and the analyses refuse or label such records.
SIMULATED_ENV = "CAEVAL_STUDY_SIMULATED_TRANSPORT"
SIMULATED_SCHEME = "simulated://"


def simulated_transport_enabled() -> bool:
    return os.environ.get(SIMULATED_ENV) == "1"


class TransportError(RuntimeError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def load_keys(path: str | Path | None = None) -> dict[str, str]:
    keys = {name: os.environ[name] for name in KEY_NAMES.values() if os.environ.get(name)}
    resolved = Path(path) if path else None
    if resolved is None and os.environ.get("MEDROBUST_KEYS_PATH"):
        resolved = Path(os.environ["MEDROBUST_KEYS_PATH"])
    if resolved is not None:
        txt = resolved.read_text(encoding="utf-8")
        for m in re.finditer(r"^([A-Z_]+_API_KEY)\s*=\s*(\S+)", txt, re.M):
            keys[m.group(1)] = m.group(2).strip()
    return keys


def require_key(provider: str, keys: dict[str, str]) -> str:
    name = KEY_NAMES.get(provider)
    if not name:
        raise ValueError(f"unsupported provider {provider!r}")
    if simulated_transport_enabled():
        return "SIMULATED-NO-KEY"
    if not keys.get(name):
        raise RuntimeError(f"missing {name}; use environment variables or --keys/MEDROBUST_KEYS_PATH")
    return keys[name]


def _http_json(
    url: str,
    headers: dict[str, str],
    payload: dict,
    timeout_seconds: int,
) -> tuple[int, dict]:
    if simulated_transport_enabled():
        from study_runtime.simulated import simulated_http
        return simulated_http(url, headers, payload)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("provider returned a non-object JSON body")
            return int(response.status), data
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except Exception:
            data = {"error": raw[:1000]}
        return int(exc.code), data
    except Exception as exc:
        raise TransportError(repr(exc)) from exc


def _responses_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return str(data["output_text"])
    parts = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") in {"output_text", "text"}:
                parts.append(str(block.get("text", "")))
    return "".join(parts)


def _anthropic_text(data: dict) -> str:
    return "".join(
        str(block.get("text", ""))
        for block in data.get("content", [])
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _google_text(data: dict) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except Exception:
        return ""
    return "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))


def _finish_reason(provider: str, data: dict) -> str:
    """Why generation stopped, in the provider's own vocabulary.

    Recorded because a 200 with text is not necessarily a complete answer: a
    response cut off at the output cap, or declined, still arrives as text.
    """
    try:
        if provider == "anthropic":
            return str(data.get("stop_reason") or "")
        if provider == "google":
            return str(data["candidates"][0].get("finishReason") or "")
        status = str(data.get("status") or "")
        detail = (data.get("incomplete_details") or {}).get("reason")
        return f"{status}:{detail}" if detail else status
    except Exception:
        return ""


COMPLETE_FINISH = {"end_turn", "stop_sequence", "STOP", "completed", ""}


def _request_for_provider(
    provider: str,
    model: str,
    system: str,
    user: str,
    key: str,
    reasoning_effort: str,
    max_output_tokens: int,
) -> tuple[str, dict[str, str], dict, callable]:
    effort = str(reasoning_effort or "provider_default").lower()
    if effort not in EFFORTS:
        raise ValueError(f"unsupported reasoning_effort {effort!r}")

    if provider == "openai":
        endpoint = "https://api.openai.com/v1/responses"
        payload = {
            "model": model,
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_output_tokens": int(max_output_tokens),
        }
        if effort != "provider_default":
            payload["reasoning"] = {"effort": effort}
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        return endpoint, headers, payload, _responses_text

    if provider == "xai":
        endpoint = "https://api.x.ai/v1/responses"
        payload = {
            "model": model,
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_output_tokens": int(max_output_tokens),
        }
        if effort != "provider_default":
            payload["reasoning"] = {"effort": effort}
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        return endpoint, headers, payload, _responses_text

    if provider == "anthropic":
        endpoint = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": model,
            "max_tokens": int(max_output_tokens),
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if effort != "provider_default":
            payload["thinking"] = {"type": "adaptive"}
            payload["output_config"] = {"effort": effort}
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        return endpoint, headers, payload, _anthropic_text

    if provider == "google":
        # The key travels in a header, never in the URL, so it cannot reach a log
        # line, an exception message or the recorded endpoint.
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": int(max_output_tokens)},
        }
        if effort != "provider_default":
            if effort == "xhigh":
                raise ValueError("Gemini thinkingLevel does not support xhigh in this study runtime")
            payload["generationConfig"]["thinkingConfig"] = {"thinkingLevel": effort}
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
        return endpoint, headers, payload, _google_text

    raise ValueError(f"unsupported provider {provider!r}")


def _provider_usage(provider: str, data: dict) -> dict:
    if provider == "google":
        return data.get("usageMetadata", {}) or {}
    return data.get("usage", {}) or {}


def call_provider(
    provider: str,
    model: str,
    system: str,
    user: str,
    keys: dict[str, str],
    *,
    reasoning_effort: str = "provider_default",
    max_output_tokens: int = 3500,
    max_attempts: int = 4,
    retry_backoff_seconds: float = 1.0,
    timeout_seconds: int = 180,
    sleep_fn=time.sleep,
) -> tuple[str, str, dict]:
    """Return (text, status, metadata) without throwing for ordinary API failures."""
    key = require_key(provider, keys)
    endpoint, headers, payload, parser = _request_for_provider(
        provider, model, system, user, key, reasoning_effort, max_output_tokens
    )
    simulated = simulated_transport_enabled()
    recorded_endpoint = (
        SIMULATED_SCHEME + endpoint.split("://", 1)[1] if simulated else endpoint
    )
    request_hash = canonical_hash({
        "endpoint": endpoint,
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "max_output_tokens": int(max_output_tokens),
        "payload": payload,
    })
    base_meta = {"simulated": simulated}
    started = utcnow()
    last_http: int | None = None
    last_error = ""
    response_data: dict = {}

    for attempt in range(1, max(1, int(max_attempts)) + 1):
        try:
            http_status, response_data = _http_json(endpoint, headers, payload, int(timeout_seconds))
            last_http = http_status
        except TransportError as exc:
            last_error = str(exc)[:1000]
            if attempt < max_attempts:
                sleep_fn(float(retry_backoff_seconds) * (2 ** (attempt - 1)))
                continue
            meta = {
                "attempts": attempt,
                "http_status": None,
                "configured_model": model,
                "resolved_model": None,
                **base_meta,
                "endpoint": recorded_endpoint,
                "reasoning_effort": reasoning_effort,
                "max_output_tokens": int(max_output_tokens),
                "request_sha256": request_hash,
                "started_at_utc": started,
                "finished_at_utc": utcnow(),
                "usage": {},
                "error_type": "transport_failure",
                "error_detail": last_error,
            }
            return "", "transport_failure", meta

        if 200 <= http_status < 300:
            text = parser(response_data).strip()
            resolved_model = (
                response_data.get("model") or response_data.get("modelVersion") or model
            )
            finish = _finish_reason(provider, response_data)
            meta = {
                "attempts": attempt,
                "http_status": http_status,
                "configured_model": model,
                "resolved_model": resolved_model,
                **base_meta,
                "endpoint": recorded_endpoint,
                "reasoning_effort": reasoning_effort,
                "max_output_tokens": int(max_output_tokens),
                "request_sha256": request_hash,
                "started_at_utc": started,
                "finished_at_utc": utcnow(),
                "usage": _provider_usage(provider, response_data),
                "error_type": None,
                "error_detail": "",
                "finish_reason": finish,
                "output_complete": finish in COMPLETE_FINISH,
            }
            if text:
                return text, "ok", meta
            meta["error_type"] = "model_output_failure"
            meta["error_detail"] = "successful API response contained no usable model text"
            return "", "model_output_failure", meta

        last_error = json.dumps(response_data, ensure_ascii=False)[:1000]
        if http_status in RETRYABLE_HTTP and attempt < max_attempts:
            sleep_fn(float(retry_backoff_seconds) * (2 ** (attempt - 1)))
            continue

        meta = {
            "attempts": attempt,
            "http_status": http_status,
            "configured_model": model,
            "resolved_model": response_data.get("model"),
            **base_meta,
            "endpoint": recorded_endpoint,
            "reasoning_effort": reasoning_effort,
            "max_output_tokens": int(max_output_tokens),
            "request_sha256": request_hash,
            "started_at_utc": started,
            "finished_at_utc": utcnow(),
            "usage": _provider_usage(provider, response_data),
            "error_type": "provider_failure",
            "error_detail": last_error,
        }
        return "", "provider_failure", meta

    raise AssertionError(f"unreachable provider loop; last_http={last_http}")
