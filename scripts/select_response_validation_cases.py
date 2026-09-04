#!/usr/bin/env python3
"""Freeze the 60-source primary response-validation cohort BEFORE target calls.

The 150-case primary casepack establishes perturbation construct validity and source
breadth. Only 60 sources are needed for the physician-powered response/criterion
validation. Selecting them before target execution avoids generating 720 unscored
target responses.

Selection is deterministic and identical to the rank previously used by the
physician-calibration script: 30 missing-information + 30 conflicting-evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

SEED = "clinical-ai-eval-physician-validation-v1|physician-calibration"
FAMILIES = ("missing_information", "conflicting_evidence")
N_PER_FAMILY = 30


def digest(*parts: str) -> str:
    return hashlib.sha256((SEED + "|" + "|".join(parts)).encode()).hexdigest()


def case_rank(case_id: str) -> str:
    return digest("shared-case-rank", case_id)


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--casepack", required=True, type=Path,
                   help="Final construct-valid 150-case private primary casepack")
    p.add_argument("--vault", required=True, type=Path)
    p.add_argument("--public-manifest", required=True, type=Path)
    p.add_argument("--cases-per-family", type=int, default=N_PER_FAMILY)
    args = p.parse_args()

    cases = read_jsonl(args.casepack)
    if len(cases) != 150 or len({str(c["case_id"]) for c in cases}) != 150:
        raise RuntimeError("primary source casepack must contain exactly 150 unique cases")

    chosen: list[dict] = []
    for family in FAMILIES:
        pool = sorted(
            [c for c in cases if str(c.get("primary_family")) == family],
            key=lambda c: case_rank(str(c["case_id"])),
        )
        if len(pool) < args.cases_per_family:
            raise RuntimeError(
                f"family {family} has {len(pool)} construct-valid cases; "
                f"needs {args.cases_per_family}"
            )
        chosen.extend(pool[: args.cases_per_family])

    chosen = sorted(chosen, key=lambda c: case_rank(str(c["case_id"])))
    expected = args.cases_per_family * len(FAMILIES)
    if len(chosen) != expected:
        raise AssertionError(f"expected {expected} response-validation sources, got {len(chosen)}")

    private_out = args.vault / "casepack" / "response_validation_60.private.jsonl"
    private_out.parent.mkdir(parents=True, exist_ok=True)
    with private_out.open("w", encoding="utf-8") as f:
        for c in chosen:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    args.public_manifest.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "case_id", "source_id", "primary_family", "construct_reviewer",
        "selection_rank_sha256", "response_validation_status",
    ]
    with args.public_manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for c in chosen:
            w.writerow({
                "case_id": c["case_id"],
                "source_id": c["source_id"],
                "primary_family": c["primary_family"],
                "construct_reviewer": c.get("construct_reviewer", ""),
                "selection_rank_sha256": case_rank(str(c["case_id"])),
                "response_validation_status": "selected_before_target_execution",
            })

    counts = {family: sum(c["primary_family"] == family for c in chosen) for family in FAMILIES}
    print(f"Frozen response-validation cohort: {len(chosen)} sources {counts}")
    print(f"Private target casepack: {private_out}")
    print(f"Public selection manifest: {args.public_manifest}")
    print("Expected target calls: 60 sources x 2 presentations x 4 targets = 480.")


if __name__ == "__main__":
    main()
