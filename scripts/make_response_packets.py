#!/usr/bin/env python3
"""Create cross-fitted reviewer-facing CSVs with no model/perturbation identifiers.

Output: response_review_<R>_wave1.csv and _wave2.csv for each reviewer.

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

    # Each reviewer necessarily rates both the original and the perturbed
    # presentation of every source they review (only two physicians are eligible
    # per source). To stop the two being compared side by side, each source's two
    # presentations go to DIFFERENT waves, at random per reviewer and source. The
    # reviewer completes and returns wave 1 before receiving wave 2.
    total_ratings = 0
    for reviewer in REVIEWERS:
        waves: dict[int, list[dict]] = {1: [], 2: []}
        for u in assigned[reviewer]:
            first = "original" if int(order_key(reviewer, "wave|" + str(u["source_id_internal"])), 16) % 2 else "perturbed"
            waves[1 if u["presentation_internal"] == first else 2].append(u)
        for wave, rows in waves.items():
            ordered = sorted(rows, key=lambda r: order_key(reviewer, str(r["review_unit_id"])))
            path = args.out_dir / f"response_review_{reviewer}_wave{wave}.csv"
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
        both_in_one = [
            sid for sid in {u["source_id_internal"] for u in assigned[reviewer]}
            if len({u["presentation_internal"] for u in waves[1] if u["source_id_internal"] == sid}) > 1
            or len({u["presentation_internal"] for u in waves[2] if u["source_id_internal"] == sid}) > 1
        ]
        if both_in_one:
            raise AssertionError(f"{reviewer}: a source has both presentations in one wave: {both_in_one[:3]}")

    if total_ratings != 2 * len(units):
        raise AssertionError(f"expected exactly two blinded ratings per unit; got {total_ratings} for {len(units)} units")
    print(f"Cross-fit packet generation complete: {len(units)} cells, {total_ratings} independent physician ratings.")


if __name__ == "__main__":
    main()
