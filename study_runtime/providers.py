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
    if not keys.get(name):
        raise RuntimeError(f"missing {name}; use environment variables or --keys/MEDROBUST_KEYS_PATH")
    return keys[name]


def _http_json(
    url: str,
    headers: dict[str, str],
    payload: dict,
    timeout_seconds: int,
) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return int(response.status), json.loads(raw)
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
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        if effort != "provider_default":
            raise ValueError(
                "Google reasoning effort is intentionally locked to provider_default in this study "
                "until a model-specific thinking parameter is independently verified."
            )
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": int(max_output_tokens)},
        }
        return endpoint, {"Content-Type": "application/json"}, payload, _google_text

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
    request_hash = canonical_hash({
        "endpoint": endpoint.split("?key=")[0],
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "max_output_tokens": int(max_output_tokens),
        "payload": payload if provider != "google" else {**payload},
    })
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
                "endpoint": endpoint.split("?key=")[0],
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
            resolved_model = response_data.get("model") or model
            meta = {
                "attempts": attempt,
                "http_status": http_status,
                "configured_model": model,
                "resolved_model": resolved_model,
                "endpoint": endpoint.split("?key=")[0],
                "reasoning_effort": reasoning_effort,
                "max_output_tokens": int(max_output_tokens),
                "request_sha256": request_hash,
                "started_at_utc": started,
                "finished_at_utc": utcnow(),
                "usage": _provider_usage(provider, response_data),
                "error_type": None,
                "error_detail": "",
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
            "endpoint": endpoint.split("?key=")[0],
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
