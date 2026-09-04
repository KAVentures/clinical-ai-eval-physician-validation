#!/usr/bin/env python3
"""Score only the frozen physician-calibration cells with the prespecified judge.

The confirmatory automated-evaluator analysis uses ONE blinded judge (Grok 4.6)
on exactly the same 480 response cells that receive physician reference labels.
This avoids spending money on unanchored automated scores and keeps the study
focused on validating Clinical-AI-Eval rather than re-running a judge-bias survey.

Judge API/transport/empty/JSON failures remain explicit missing measurements and
are never converted to a negative/safe label.
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


def judge_user(case_text: str, response_text: str) -> str:
    return (
        "CASE / QUESTION (exactly as the target system received it):\n"
        + str(case_text)
        + "\n\nTARGET RESPONSE TO SCORE:\n"
        + str(response_text)
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--units", required=True, type=Path,
                   help="Frozen physician_calibration_units.private.jsonl (480 primary cells)")
    p.add_argument("--models", required=True, type=Path)
    p.add_argument("--vault", required=True, type=Path)
    p.add_argument("--keys", type=Path)
    p.add_argument("--public-manifest", required=True, type=Path)
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()

    cfg = yaml.safe_load(args.models.read_text(encoding="utf-8"))
    if not cfg.get("frozen"):
        raise RuntimeError("model/judge configuration must be frozen before judge execution")

    judges = list(cfg.get("primary_judges") or [])
    if len(judges) != 1:
        raise RuntimeError(f"confirmatory study requires exactly one primary automated judge; got {len(judges)}")
    judge = judges[0]
    if judge.get("mode", "blinded") != "blinded":
        raise RuntimeError("primary automated judge must be blinded")
    if str(judge.get("provider")) != "xai" or str(judge.get("model")) != "grok-4.6":
        raise RuntimeError("locked design expects xAI Grok 4.6 as the primary automated judge")

    units = read_jsonl(args.units)
    expected = int((cfg.get("automated_judge_selection") or {}).get("expected_primary_cells", 480))
    if len(units) != expected or len({str(u["review_unit_id"]) for u in units}) != expected:
        raise RuntimeError(f"judge input must be exactly {expected} unique physician-calibration cells")

    policy = cfg.get("inference_policy") or {}
    keys = load_keys(args.keys)
    system = (Path(__file__).resolve().parents[1] / "prompts" / "judge_prompt.txt").read_text(encoding="utf-8")

    private_out = args.vault / "judges" / "judge_scores.private.jsonl"
    private_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_manifest.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict] = {}
    if args.resume:
        for r in read_jsonl(private_out):
            existing[str(r["judge_evaluation_id"])] = r
    records = dict(existing)

    for u in units:
        response_id = str(u["response_id_internal"])
        eid = f"{response_id}::{judge['judge_id']}"
        if eid in records and records[eid].get("status") in {"ok", "not_scored_target_output_failure"}:
            continue

        if str(u.get("target_status_internal", "ok")) != "ok":
            records[eid] = {
                "judge_evaluation_id": eid,
                "review_unit_id": u["review_unit_id"],
                "response_id": response_id,
                "case_id": u["case_id_internal"],
                "source_id": u["source_id_internal"],
                "presentation": u["presentation_internal"],
                "primary_family": u["primary_family_internal"],
                "target_id": u["target_id_internal"],
                "target_provider": u.get("target_provider_internal", ""),
                "same_provider_target_judge": bool(u.get("target_provider_internal") == judge["provider"]),
                "judge_id": judge["judge_id"],
                "judge_provider": judge["provider"],
                "judge_model": judge["model"],
                "judge_mode": "blinded",
                "judge_reasoning_effort": judge.get("reasoning_effort", "provider_default"),
                "score": None,
                "status": "not_scored_target_output_failure",
                "parse_error": "",
                "provider_meta": {},
            }
            print(eid, "not_scored_target_output_failure")
            continue

        text, api_status, meta = call_provider(
            judge["provider"],
            judge["model"],
            system,
            judge_user(str(u["case_text"]), str(u["response_text"])),
            keys,
            reasoning_effort=str(judge.get("reasoning_effort", "provider_default")),
            max_output_tokens=int(policy.get("judge_max_output_tokens", 12000)),
            max_attempts=int(policy.get("max_attempts", 4)),
            retry_backoff_seconds=float(policy.get("retry_backoff_seconds", 1.0)),
            timeout_seconds=int(policy.get("timeout_seconds", 600)),
        )

        score = None
        parse_error = ""
        if api_status != "ok":
            status = "judge_" + api_status
        else:
            try:
                score = parse_judge_json(text)
                status = "ok"
            except Exception as exc:
                status = "judge_parse_failure"
                parse_error = repr(exc)[:1000]

        records[eid] = {
            "judge_evaluation_id": eid,
            "review_unit_id": u["review_unit_id"],
            "response_id": response_id,
            "case_id": u["case_id_internal"],
            "source_id": u["source_id_internal"],
            "presentation": u["presentation_internal"],
            "primary_family": u["primary_family_internal"],
            "target_id": u["target_id_internal"],
            "target_provider": u.get("target_provider_internal", ""),
            "same_provider_target_judge": bool(u.get("target_provider_internal") == judge["provider"]),
            "judge_id": judge["judge_id"],
            "judge_provider": judge["provider"],
            "judge_model": judge["model"],
            "judge_mode": "blinded",
            "judge_reasoning_effort": judge.get("reasoning_effort", "provider_default"),
            "score": score,
            "status": status,
            "parse_error": parse_error,
            "provider_meta": meta,
        }
        print(eid, status)

    with private_out.open("w", encoding="utf-8") as pf:
        for eid in sorted(records):
            pf.write(json.dumps(records[eid], ensure_ascii=False) + "\n")

    fields = [
        "judge_evaluation_id", "review_unit_id", "response_id", "case_id",
        "presentation", "primary_family", "target_id", "target_provider",
        "same_provider_target_judge", "judge_id", "judge_provider",
        "configured_model", "resolved_model", "judge_mode", "reasoning_effort",
        "request_sha256", "attempts", "http_status", "score_sha256", "status",
    ]
    with args.public_manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for eid in sorted(records):
            r = records[eid]
            pm = r.get("provider_meta") or {}
            w.writerow({
                "judge_evaluation_id": eid,
                "review_unit_id": r["review_unit_id"],
                "response_id": r["response_id"],
                "case_id": r["case_id"],
                "presentation": r["presentation"],
                "primary_family": r["primary_family"],
                "target_id": r["target_id"],
                "target_provider": r["target_provider"],
                "same_provider_target_judge": str(r["same_provider_target_judge"]).lower(),
                "judge_id": r["judge_id"],
                "judge_provider": r["judge_provider"],
                "configured_model": r["judge_model"],
                "resolved_model": pm.get("resolved_model") or "",
                "judge_mode": r["judge_mode"],
                "reasoning_effort": r.get("judge_reasoning_effort", ""),
                "request_sha256": pm.get("request_sha256") or "",
                "attempts": pm.get("attempts") or "",
                "http_status": pm.get("http_status") if pm.get("http_status") is not None else "",
                "score_sha256": sha_obj(r["score"]) if r.get("score") is not None else "",
                "status": r["status"],
            })

    counts: dict[str, int] = {}
    for r in records.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"Primary automated-judge cells: {len(records)} / expected {expected}")
    print(f"Status counts: {counts}")
    if len(records) != expected:
        raise RuntimeError(f"expected {expected} judge evaluations, found {len(records)}")
    if any(k != "ok" for k in counts):
        print("Judge failures remain explicit missing measurements; rerun infrastructure failures with --resume where appropriate.")


if __name__ == "__main__":
    main()
