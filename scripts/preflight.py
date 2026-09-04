#!/usr/bin/env python3
"""Fail-closed preflight checks for authoring, target, judge and analysis phases."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import yaml

from study_runtime.providers import KEY_NAMES, load_keys


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def require_keys(providers: set[str], key_path: Path | None) -> None:
    keys = load_keys(key_path)
    missing = [KEY_NAMES[p] for p in sorted(providers) if not keys.get(KEY_NAMES[p])]
    if missing:
        raise RuntimeError("missing required API credentials: " + ", ".join(missing))


def check_config(cfg: dict) -> None:
    targets = cfg.get("target_models") or []
    judges = cfg.get("primary_judges") or []
    if len(targets) != 4 or len({x["provider"] for x in targets}) != 4:
        raise RuntimeError("need four targets from four distinct providers")
    if len(judges) != 1:
        raise RuntimeError("confirmatory study requires exactly one primary automated judge")
    if judges[0].get("provider") != "xai" or judges[0].get("model") != "grok-4.6":
        raise RuntimeError("primary automated judge must be xAI Grok 4.6")
    if any(x.get("mode") != "blinded" for x in judges):
        raise RuntimeError("all primary judges must be blinded")
    if cfg.get("inference_policy", {}).get("tools") != "disabled":
        raise RuntimeError("tools must be disabled for the locked primary study")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--phase", required=True, choices=["authoring", "targets", "judges", "analysis"])
    p.add_argument("--models", type=Path, default=Path("configs/model_panel.yaml"))
    p.add_argument("--keys", type=Path)
    p.add_argument("--vault", type=Path)
    p.add_argument("--casepack-manifest", type=Path, default=Path("data/primary_casepack_manifest.csv"))
    p.add_argument("--response-validation-manifest", type=Path,
                   default=Path("data/response_validation_case_selection.csv"))
    p.add_argument("--responses-manifest", type=Path, default=Path("data/target_response_manifest.csv"))
    p.add_argument("--calibration-manifest", type=Path, default=Path("data/physician_calibration_selection.csv"))
    args = p.parse_args()

    cfg = yaml.safe_load(args.models.read_text(encoding="utf-8"))
    check_config(cfg)

    if args.phase == "authoring":
        require_keys({cfg["authoring_model"]["provider"]}, args.keys)
        if cfg.get("authoring_frozen") is not True:
            raise RuntimeError("authoring_frozen is false; only technical limited dry-runs are allowed")
        print("PASS authoring preflight")
        return

    if cfg.get("frozen") is not True:
        raise RuntimeError("model panel is not frozen")
    if args.phase == "targets":
        require_keys({x["provider"] for x in cfg.get("target_models", [])}, args.keys)
    else:
        require_keys({x["provider"] for x in cfg.get("primary_judges", [])}, args.keys)

    case_rows = read_csv(args.casepack_manifest)
    if len(case_rows) != 150:
        raise RuntimeError(f"primary casepack manifest must contain 150 rows, got {len(case_rows)}")
    if len({r["case_id"] for r in case_rows}) != 150:
        raise RuntimeError("primary casepack contains duplicate case IDs")

    response_selection = read_csv(args.response_validation_manifest)
    if len(response_selection) != 60 or len({r["case_id"] for r in response_selection}) != 60:
        raise RuntimeError(
            f"response-validation manifest must contain 60 unique source cases, got {len(response_selection)}")
    family_counts = {}
    for row in response_selection:
        family_counts[row["primary_family"]] = family_counts.get(row["primary_family"], 0) + 1
    if family_counts != {"missing_information": 30, "conflicting_evidence": 30}:
        raise RuntimeError(f"response-validation family balance must be 30/30, got {family_counts}")

    if args.phase == "targets":
        print("PASS target preflight")
        return

    response_rows = read_csv(args.responses_manifest)
    if len(response_rows) != 480:
        raise RuntimeError(f"target response manifest must contain 480 cells, got {len(response_rows)}")
    infra = [r for r in response_rows if r["status"] in {"transport_failure", "provider_failure"}]
    if infra:
        raise RuntimeError(f"{len(infra)} infrastructure/provider failures remain; resume target execution first")
    allowed = {"ok", "model_output_failure"}
    unexpected = sorted({r["status"] for r in response_rows if r["status"] not in allowed})
    if unexpected:
        raise RuntimeError(f"unexpected target statuses: {unexpected}")

    cal = read_csv(args.calibration_manifest)
    if len(cal) != 480:
        raise RuntimeError(f"primary physician calibration manifest must contain 480 response cells, got {len(cal)}")
    if len({r["review_unit_id"] for r in cal}) != 480:
        raise RuntimeError("duplicate calibration review-unit IDs")
    for row in cal:
        pair = set(str(row["response_reviewer_pair"]).split("+"))
        if row["construct_reviewer"] in pair or len(pair) != 2:
            raise RuntimeError(f"cross-fit leakage in calibration row {row['review_unit_id']}")

    if args.phase == "judges":
        print("PASS judge preflight")
        return

    if args.vault is None:
        raise RuntimeError("--vault is required for analysis preflight")
    physician_ref = args.vault / "review" / "physician_reference.private.csv"
    judge_scores = args.vault / "judges" / "judge_scores.private.jsonl"
    if not physician_ref.exists():
        raise RuntimeError("physician reference file not finalized")
    refs = read_csv(physician_ref)
    if len(refs) != 480:
        raise RuntimeError(f"physician reference must contain 480 cells, got {len(refs)}")
    js = read_jsonl(judge_scores)
    if len(js) != 480:
        raise RuntimeError(f"primary judge score file must contain exactly 480 calibration evaluations, got {len(js)}")
    if len({str(r.get("response_id")) for r in js}) != 480:
        raise RuntimeError("primary judge score file contains duplicate/missing response IDs")
    print("PASS analysis preflight")


if __name__ == "__main__":
    main()
