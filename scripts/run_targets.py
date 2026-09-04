#!/usr/bin/env python3
"""Run the locked target-model panel with reproducible provider provenance.

Transport/provider failures are distinct from successful-but-empty model outputs.
With --resume, only terminal model outcomes (ok/model_output_failure) are skipped;
transport/provider failures are retried and replaced rather than duplicated.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import yaml

from study_runtime.providers import call_provider, load_keys

TERMINAL = {"ok", "model_output_failure"}


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--casepack", required=True, type=Path)
    p.add_argument("--models", required=True, type=Path)
    p.add_argument("--vault", required=True, type=Path)
    p.add_argument("--keys", type=Path)
    p.add_argument("--public-manifest", required=True, type=Path)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--allow-unfrozen", action="store_true", help="Dry-run only; never use for primary study results")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    cfg = yaml.safe_load(args.models.read_text(encoding="utf-8"))
    if not cfg.get("frozen") and not args.allow_unfrozen:
        raise RuntimeError("model panel is not frozen; dry-run first, then freeze before primary execution")

    targets = cfg.get("target_models") or []
    if len(targets) != 4 or len({t.get("provider") for t in targets}) != 4:
        raise RuntimeError("protocol expects exactly four target models from four distinct providers")

    policy = cfg.get("inference_policy") or {}
    max_attempts = int(policy.get("max_attempts", 4))
    backoff = float(policy.get("retry_backoff_seconds", 1.0))
    timeout = int(policy.get("timeout_seconds", 180))
    max_tokens = int(policy.get("target_max_output_tokens", 3500))

    keys = load_keys(args.keys)
    cases = read_jsonl(args.casepack)
    if args.limit:
        cases = cases[: args.limit]
    system = (Path(__file__).resolve().parents[1] / "prompts" / "target_system_prompt.txt").read_text(encoding="utf-8")

    private_out = args.vault / "responses" / "target_responses.private.jsonl"
    private_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_manifest.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict] = {}
    if args.resume:
        for row in read_jsonl(private_out):
            existing[str(row["response_id"])] = row

    records = dict(existing)
    for case in cases:
        meta = case.get("source_metadata") or {}
        for presentation in ("original", "perturbed"):
            input_text = case["original_case"] if presentation == "original" else case["perturbed_case"]
            for target in targets:
                response_id = f"{case['case_id']}::{presentation}::{target['target_id']}"
                if response_id in records and records[response_id].get("status") in TERMINAL:
                    continue

                text, status, provider_meta = call_provider(
                    target["provider"],
                    target["model"],
                    system,
                    input_text,
                    keys,
                    reasoning_effort=str(target.get("reasoning_effort", "provider_default")),
                    max_output_tokens=max_tokens,
                    max_attempts=max_attempts,
                    retry_backoff_seconds=backoff,
                    timeout_seconds=timeout,
                )
                records[response_id] = {
                    "response_id": response_id,
                    "case_id": case["case_id"],
                    "source_id": case["source_id"],
                    "source_dataset": case.get("source_dataset", ""),
                    "source_type": meta.get("type", ""),
                    "source_difficulty": meta.get("difficulty", ""),
                    "specialty": meta.get("specialty", ""),
                    "construct_reviewer": case.get("construct_reviewer", ""),
                    "primary_family": case["primary_family"],
                    "presentation": presentation,
                    "target_id": target["target_id"],
                    "target_provider": target["provider"],
                    "target_model": target["model"],
                    "input_text": input_text,
                    "response_text": text,
                    "status": status,
                    "provider_meta": provider_meta,
                }
                print(response_id, status)

    # Rewrite atomically at the logical-record level so retried failures do not
    # leave duplicate response IDs in the frozen private file.
    with private_out.open("w", encoding="utf-8") as pf:
        for response_id in sorted(records):
            pf.write(json.dumps(records[response_id], ensure_ascii=False) + "\n")

    fields = [
        "response_id", "case_id", "source_id", "source_dataset", "primary_family",
        "presentation", "target_id", "target_provider", "configured_model",
        "resolved_model", "reasoning_effort", "max_output_tokens", "endpoint",
        "request_sha256", "attempts", "http_status", "input_sha256", "response_sha256",
        "status", "usage_json",
    ]
    with args.public_manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for response_id in sorted(records):
            r = records[response_id]
            pm = r.get("provider_meta") or {}
            w.writerow({
                "response_id": response_id,
                "case_id": r["case_id"],
                "source_id": r["source_id"],
                "source_dataset": r.get("source_dataset", ""),
                "primary_family": r["primary_family"],
                "presentation": r["presentation"],
                "target_id": r["target_id"],
                "target_provider": r["target_provider"],
                "configured_model": r["target_model"],
                "resolved_model": pm.get("resolved_model") or "",
                "reasoning_effort": pm.get("reasoning_effort") or "",
                "max_output_tokens": pm.get("max_output_tokens") or "",
                "endpoint": pm.get("endpoint") or "",
                "request_sha256": pm.get("request_sha256") or "",
                "attempts": pm.get("attempts") or "",
                "http_status": pm.get("http_status") if pm.get("http_status") is not None else "",
                "input_sha256": sha(r["input_text"]),
                "response_sha256": sha(r["response_text"]),
                "status": r["status"],
                "usage_json": json.dumps(pm.get("usage", {}), sort_keys=True),
            })

    counts: dict[str, int] = {}
    for r in records.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"Private responses: {private_out}")
    print(f"Public response manifest: {args.public_manifest}")
    print(f"Status counts: {counts}")
    if any(k in counts for k in ("transport_failure", "provider_failure")):
        print("STOP: infrastructure/API failures remain. Resolve and --resume before calibration selection.")


if __name__ == "__main__":
    main()
