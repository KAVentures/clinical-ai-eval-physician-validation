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


from caeval.score import parse_judge_json
from study_runtime.journal import append_record, compact, load_latest, refuse_overwrite
from study_runtime.lock import require_lock
from study_runtime.panel import load_panel, require_valid
from study_runtime.providers import call_provider, entry_vendor, load_keys


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
    p.add_argument("--lock", type=Path, default=Path("data/study_lock.json"),
                   help="Study lock; every locked file is re-hashed before anything runs")
    p.add_argument("--rehearsal", action="store_true", help="Accept a rehearsal lock (offline rehearsal only)")
    args = p.parse_args()

    cfg = load_panel(args.models)
    registry = require_valid(cfg)
    if not cfg.get("frozen"):
        raise RuntimeError("model/judge configuration must be frozen before judge execution")

    require_lock(args.lock, allow_rehearsal=args.rehearsal)
    judges = list(cfg.get("primary_judges") or [])
    if len(judges) != 1:
        raise RuntimeError(f"confirmatory study requires exactly one primary automated judge; got {len(judges)}")
    judge = judges[0]
    if judge.get("mode", "blinded") != "blinded":
        raise RuntimeError("primary automated judge must be blinded")
    # The judge is whatever the frozen panel names; the study lock guarantees it
    # cannot change after lock.
    judge_vendor = entry_vendor(judge, registry)
    print(f"Primary judge: {judge['judge_id']} = {judge['provider']}/{judge['model']} (developer {judge_vendor})")

    units = read_jsonl(args.units)
    expected = int((cfg.get("automated_judge_selection") or {}).get("expected_primary_cells", 480))
    if len(units) != expected or len({str(u["review_unit_id"]) for u in units}) != expected:
        raise RuntimeError(f"judge input must be exactly {expected} unique physician-calibration cells")

    policy = cfg.get("inference_policy") or {}
    keys = load_keys(args.keys, registry)
    format_attempts = max(1, int(policy.get("judge_format_attempts", 1)))
    system = (Path(__file__).resolve().parents[1] / "prompts" / "judge_prompt.txt").read_text(encoding="utf-8")

    private_out = args.vault / "judges" / "judge_scores.private.jsonl"
    private_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_manifest.parent.mkdir(parents=True, exist_ok=True)

    refuse_overwrite(private_out, args.resume, "judge scores")
    records = load_latest(private_out, "judge_evaluation_id")

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
                "same_provider_target_judge": bool(u.get("target_provider_internal") == judge_vendor),
                "judge_id": judge["judge_id"],
                "judge_provider": judge_vendor,
            "judge_api_provider": judge["provider"],
                "judge_model": judge["model"],
                "judge_mode": "blinded",
                "judge_reasoning_effort": judge.get("reasoning_effort", "provider_default"),
                "score": None,
                "status": "not_scored_target_output_failure",
                "parse_error": "",
                "provider_meta": {},
            }
            append_record(private_out, records[eid])
            print(eid, "not_scored_target_output_failure")
            continue

        # A format retry re-asks ONLY when the previous answer could not be parsed.
        # A parseable answer is never discarded, so retrying cannot steer labels; it
        # only reduces missing measurements. Every attempt is recorded.
        score, status, parse_error, meta = None, "", "", {}
        attempt_log = []
        for format_attempt in range(1, format_attempts + 1):
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
                registry=registry,
            )
            if api_status != "ok":
                status, parse_error = "judge_" + api_status, ""
                attempt_log.append({"format_attempt": format_attempt, "status": status})
                break
            try:
                score = parse_judge_json(text)
                status, parse_error = "ok", ""
                attempt_log.append({"format_attempt": format_attempt, "status": "ok"})
                break
            except Exception as exc:
                status, parse_error = "judge_parse_failure", repr(exc)[:1000]
                attempt_log.append({"format_attempt": format_attempt, "status": status,
                                    "parse_error": parse_error,
                                    "output_sha256": hashlib.sha256(text.encode()).hexdigest()})
        meta = {**(meta or {}), "format_attempts": attempt_log}

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
            "same_provider_target_judge": bool(u.get("target_provider_internal") == judge_vendor),
            "judge_id": judge["judge_id"],
            "judge_provider": judge_vendor,
            "judge_api_provider": judge["provider"],
            "judge_model": judge["model"],
            "judge_mode": "blinded",
            "judge_reasoning_effort": judge.get("reasoning_effort", "provider_default"),
            "score": score,
            "status": status,
            "parse_error": parse_error,
            "provider_meta": meta,
        }
        append_record(private_out, records[eid])
        print(eid, status)

    compact(private_out, records)

    fields = [
        "judge_evaluation_id", "review_unit_id", "response_id", "case_id",
        "presentation", "primary_family", "target_id", "target_provider",
        "same_provider_target_judge", "judge_id", "judge_provider",
        "configured_model", "resolved_model", "judge_mode", "reasoning_effort",
        "request_sha256", "attempts", "http_status", "simulated", "score_sha256", "status",
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
                "simulated": str(bool(pm.get("simulated", False))).lower(),
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
