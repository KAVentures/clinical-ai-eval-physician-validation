#!/usr/bin/env python3
"""Create cross-fitted reviewer-facing CSVs with no model/perturbation identifiers.

Each calibration unit already carries the two physicians who were NOT exposed to
that source's construct-validation pair. This script whitelists reviewer-facing
fields and refuses to send a unit to its construct reviewer.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

REVIEWERS = ("A", "B", "C")
FIELDS = [
    "review_unit_id", "case_text", "response_text", "reviewer_id",
    "unsafe_overconfident", "potentially_harmful_treatment",
    "recognizes_information_problem", "guideline_concordant_next_step",
    "excessive_abstention", "clinically_helpful", "cannot_determine_reason",
    "notes", "reviewed_at_utc",
]
SEED = "clinical-ai-eval-physician-validation-v1|response-review-order"


def order_key(reviewer: str, unit_id: str) -> str:
    return hashlib.sha256(f"{SEED}|{reviewer}|{unit_id}".encode()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--units", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    args = p.parse_args()

    units = read_jsonl(args.units)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    assigned: dict[str, list[dict]] = {r: [] for r in REVIEWERS}
    for u in units:
        construct = str(u.get("construct_reviewer_internal", ""))
        response_reviewers = tuple(u.get("response_reviewers_internal") or [])
        if construct not in REVIEWERS:
            raise RuntimeError(f"{u.get('review_unit_id')}: invalid construct reviewer")
        if len(response_reviewers) != 2 or set(response_reviewers) != (set(REVIEWERS) - {construct}):
            raise RuntimeError(f"{u.get('review_unit_id')}: response-review pair violates cross-fit blinding")
        for reviewer in response_reviewers:
            assigned[reviewer].append(u)

    total_ratings = 0
    for reviewer in REVIEWERS:
        ordered = sorted(assigned[reviewer], key=lambda r: order_key(reviewer, str(r["review_unit_id"])))
        path = args.out_dir / f"response_review_{reviewer}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for u in ordered:
                w.writerow({
                    "review_unit_id": u["review_unit_id"],
                    "case_text": u["case_text"],
                    "response_text": u["response_text"],
                    "reviewer_id": reviewer,
                    "unsafe_overconfident": "",
                    "potentially_harmful_treatment": "",
                    "recognizes_information_problem": "",
                    "guideline_concordant_next_step": "",
                    "excessive_abstention": "",
                    "clinically_helpful": "",
                    "cannot_determine_reason": "",
                    "notes": "",
                    "reviewed_at_utc": "",
                })
        total_ratings += len(ordered)
        print(f"{path}: {len(ordered)} ratings")

    if total_ratings != 2 * len(units):
        raise AssertionError(f"expected exactly two blinded ratings per unit; got {total_ratings} for {len(units)} units")
    print(f"Cross-fit packet generation complete: {len(units)} cells, {total_ratings} independent physician ratings.")


if __name__ == "__main__":
    main()
