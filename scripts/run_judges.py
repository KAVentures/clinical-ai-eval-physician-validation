#!/usr/bin/env python3
"""Score frozen target responses with the prespecified automated judge panel.

Provider/transport failures and malformed judge JSON are recorded per cell instead
of terminating the run. Reasoning effort and resolved model IDs are preserved.
Blinded and cued judge modes remain separate endpoints.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import yaml

from caeval.score import parse_judge_json
from study_runtime.providers import call_provider, load_keys


def read_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def sha_obj(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def judge_user(record: dict, mode: str) -> str:
    parts = [
        "CASE / QUESTION (exactly as the target system received it):\n" + str(record.get("input_text", "")),
        "TARGET RESPONSE TO SCORE:\n" + str(record.get("response_text", "")),
    ]
    if mode == "rubric_aware":
        parts.append(
            "DEFECT SPECIFICATION FOR THIS SECONDARY CUED ANALYSIS:\n"
            + "perturbation: " + str(record.get("perturbation_type", ""))
            + "\nchanged/withheld evidence: "
            + str(record.get("expected_missing_evidence", "") or "(none; original case)")
        )
    elif mode != "blinded":
        raise ValueError(f"unsupported judge mode {mode!r}")
    return "\n\n".join(parts)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--responses", required=True, type=Path)
    p.add_argument("--casepack", required=True, type=Path)
    p.add_argument("--models", required=True, type=Path)
    p.add_argument("--vault", required=True, type=Path)
    p.add_argument("--keys", type=Path)
    p.add_argument("--public-manifest", required=True, type=Path)
    p.add_argument("--include-secondary", action="store_true")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()

    cfg = yaml.safe_load(args.models.read_text(encoding="utf-8"))
    if not cfg.get("frozen"):
        raise RuntimeError("model panel must be frozen before judge execution")

    judges = list(cfg.get("primary_judges") or [])
    if len(judges) != 3 or len({j["provider"] for j in judges}) != 3:
        raise RuntimeError("primary judge panel must contain three distinct providers")
    if any(j.get("mode", "blinded") != "blinded" for j in judges):
        raise RuntimeError("all primary judges must be blinded")
    if args.include_secondary:
        judges.extend(cfg.get("secondary_judges") or [])
    if len({j["judge_id"] for j in judges}) != len(judges):
        raise RuntimeError("duplicate judge_id")

    policy = cfg.get("inference_policy") or {}
    keys = load_keys(args.keys)
    responses = read_jsonl(args.responses)
    cases = {str(c["case_id"]): c for c in read_jsonl(args.casepack)}
    system = (Path(__file__).resolve().parents[1] / "prompts" / "judge_prompt.txt").read_text(encoding="utf-8")

    private_out = args.vault / "judges" / "judge_scores.private.jsonl"
    private_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_manifest.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict] = {}
    if args.resume:
        for r in read_jsonl(private_out):
            existing[str(r["judge_evaluation_id"])] = r
    records = dict(existing)

    max_format_attempts = int(policy.get("judge_format_attempts", 2))
    for r in responses:
        case = cases[str(r["case_id"])]
        perturbation_type = "original" if r["presentation"] == "original" else case["primary_family"]
        changed_evidence = "" if r["presentation"] == "original" else case.get("changed_evidence", "")
        base_record = {
            "input_text": r["input_text"],
            "response_text": r["response_text"],
            "perturbation_type": perturbation_type,
            "expected_missing_evidence": changed_evidence,
        }

        for j in judges:
            eid = f"{r['response_id']}::{j['judge_id']}"
            if eid in records and records[eid].get("status") == "ok":
                continue

            mode = str(j.get("mode", "blinded"))
            score = None
            final_status = "judge_parse_failure"
            call_metas = []
            parse_error = ""
            for format_attempt in range(1, max_format_attempts + 1):
                text, api_status, meta = call_provider(
                    j["provider"],
                    j["model"],
                    system,
                    judge_user(base_record, mode),
                    keys,
                    reasoning_effort=str(j.get("reasoning_effort", "provider_default")),
                    max_output_tokens=int(policy.get("judge_max_output_tokens", 2500)),
                    max_attempts=int(policy.get("max_attempts", 4)),
                    retry_backoff_seconds=float(policy.get("retry_backoff_seconds", 1.0)),
                    timeout_seconds=int(policy.get("timeout_seconds", 180)),
                )
                call_metas.append(meta)
                if api_status != "ok":
                    final_status = "judge_" + api_status
                    break
                try:
                    score = parse_judge_json(text)
                    final_status = "ok"
                    break
                except Exception as exc:
                    parse_error = repr(exc)[:1000]
                    final_status = "judge_parse_failure"

            last_meta = call_metas[-1] if call_metas else {}
            records[eid] = {
                "judge_evaluation_id": eid,
                "response_id": r["response_id"],
                "case_id": r["case_id"],
                "source_id": r["source_id"],
                "presentation": r["presentation"],
                "primary_family": r["primary_family"],
                "target_id": r["target_id"],
                "target_provider": r["target_provider"],
                "judge_id": j["judge_id"],
                "judge_provider": j["provider"],
                "judge_model": j["model"],
                "judge_mode": mode,
                "judge_reasoning_effort": j.get("reasoning_effort", "provider_default"),
                "score": score,
                "status": final_status,
                "format_attempts": len(call_metas),
                "parse_error": parse_error,
                "provider_meta": last_meta,
                "provider_attempt_history": call_metas,
            }
            print(eid, final_status)

    with private_out.open("w", encoding="utf-8") as pf:
        for eid in sorted(records):
            pf.write(json.dumps(records[eid], ensure_ascii=False) + "\n")

    fields = [
        "judge_evaluation_id", "response_id", "case_id", "presentation", "primary_family",
        "target_id", "target_provider", "judge_id", "judge_provider", "configured_model",
        "resolved_model", "judge_mode", "reasoning_effort", "request_sha256",
        "format_attempts", "http_status", "score_sha256", "status",
    ]
    with args.public_manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for eid in sorted(records):
            r = records[eid]
            pm = r.get("provider_meta") or {}
            w.writerow({
                "judge_evaluation_id": eid,
                "response_id": r["response_id"],
                "case_id": r["case_id"],
                "presentation": r["presentation"],
                "primary_family": r["primary_family"],
                "target_id": r["target_id"],
                "target_provider": r["target_provider"],
                "judge_id": r["judge_id"],
                "judge_provider": r["judge_provider"],
                "configured_model": r["judge_model"],
                "resolved_model": pm.get("resolved_model") or "",
                "judge_mode": r["judge_mode"],
                "reasoning_effort": r.get("judge_reasoning_effort", ""),
                "request_sha256": pm.get("request_sha256") or "",
                "format_attempts": r.get("format_attempts", ""),
                "http_status": pm.get("http_status") if pm.get("http_status") is not None else "",
                "score_sha256": sha_obj(r["score"]) if r.get("score") is not None else "",
                "status": r["status"],
            })

    counts: dict[str, int] = {}
    for r in records.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"Private judge scores: {private_out}")
    print(f"Public judge manifest: {args.public_manifest}")
    print(f"Status counts: {counts}")
    if any(k != "ok" for k in counts):
        print("Judge failures remain explicit; primary analyses must report their denominator and may not coerce them negative.")


if __name__ == "__main__":
    main()
