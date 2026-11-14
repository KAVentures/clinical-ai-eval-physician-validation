#!/usr/bin/env python3
"""Live endpoint check for every configured author, target and judge model.

Sends ONE harmless non-study prompt per distinct (provider, model, effort) through
the same runtime the study uses, and reports what came back: status, the model ID
the provider says it served, finish reason, attempts. Run it with study credentials
immediately before setting `frozen: true`. It writes no case text anywhere.

Exit status is non-zero if any configured model does not answer, so a wrong model
ID or an unsupported reasoning setting is found now and not at cell 1 of 480.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import yaml

from study_runtime.providers import call_provider, load_keys

SYSTEM = "You are a connectivity check. Follow the instruction exactly."
USER = "Reply with the single word: ready"


def configured(cfg: dict) -> list[tuple[str, str, str, str]]:
    rows = []
    author = cfg.get("authoring_model") or {}
    if author:
        rows.append(("author", author["provider"], author["model"],
                     str(author.get("reasoning_effort", "provider_default"))))
    for t in cfg.get("target_models") or []:
        rows.append((f"target:{t['target_id']}", t["provider"], t["model"],
                     str(t.get("reasoning_effort", "provider_default"))))
    for j in [*(cfg.get("primary_judges") or []), *(cfg.get("secondary_judges") or [])]:
        rows.append((f"judge:{j['judge_id']}", j["provider"], j["model"],
                     str(j.get("reasoning_effort", "provider_default"))))
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--models", type=Path, default=Path("configs/model_panel.yaml"))
    p.add_argument("--keys", type=Path)
    p.add_argument("--out", type=Path, default=Path("data/provider_smoke_test.csv"))
    args = p.parse_args()

    cfg = yaml.safe_load(args.models.read_text(encoding="utf-8"))
    policy = cfg.get("inference_policy") or {}
    keys = load_keys(args.keys)
    fields = ["role", "provider", "configured_model", "reasoning_effort", "status", "resolved_model",
              "http_status", "attempts", "finish_reason", "output_complete", "simulated",
              "request_sha256", "checked_at_utc", "error_detail"]
    out_rows, cache = [], {}
    for role, provider, model, effort in configured(cfg):
        key = (provider, model, effort)
        if key not in cache:
            try:
                _, status, meta = call_provider(
                    provider, model, SYSTEM, USER, keys,
                    reasoning_effort=effort,
                    max_output_tokens=int(policy.get("target_max_output_tokens", 3500)),
                    max_attempts=int(policy.get("max_attempts", 4)),
                    retry_backoff_seconds=float(policy.get("retry_backoff_seconds", 1.0)),
                    timeout_seconds=int(policy.get("timeout_seconds", 180)),
                )
            except (RuntimeError, ValueError) as exc:   # missing key, unsupported setting
                status, meta = "not_attempted", {"error_detail": str(exc)}
            cache[key] = (status, meta)
        status, meta = cache[key]
        out_rows.append({
            "role": role, "provider": provider, "configured_model": model,
            "reasoning_effort": effort, "status": status,
            "resolved_model": meta.get("resolved_model") or "",
            "http_status": meta.get("http_status") if meta.get("http_status") is not None else "",
            "attempts": meta.get("attempts", ""),
            "finish_reason": meta.get("finish_reason", ""),
            "output_complete": meta.get("output_complete", ""),
            "simulated": str(bool(meta.get("simulated", False))).lower(),
            "request_sha256": meta.get("request_sha256", ""),
            "checked_at_utc": meta.get("finished_at_utc", ""),
            "error_detail": str(meta.get("error_detail", ""))[:300],
        })
        print(f"{status:22} {role:34} {provider}/{model} effort={effort} "
              f"resolved={meta.get('resolved_model') or '-'}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    print(f"Wrote {args.out}")
    bad = [r for r in out_rows if r["status"] != "ok"]
    if bad:
        sys.exit(f"{len(bad)} of {len(out_rows)} configured models did not answer. Do not freeze the panel.")
    print("All configured models answered. Compare resolved_model with the IDs you intend to freeze.")


if __name__ == "__main__":
    main()
