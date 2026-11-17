#!/usr/bin/env python3
"""Create a post-response construct-reliability audit on 30 calibration cases.

Must be run only after the physician reference file exists. The second construct
reviewer is chosen from the two physicians who already completed blinded response
ratings for that case, so later exposure cannot contaminate those locked labels.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

SEED = "clinical-ai-eval-physician-validation-v1|construct-reliability-audit"
N_AUDIT = 30
FIELDS = [
    "case_id", "source_id", "family", "original_case", "perturbed_case",
    "reviewer_id", "original_coherent", "perturbed_coherent",
    "same_patient_task_timepoint", "evidence_load_bearing", "construct_achieved",
    "safe_response_definable", "decision", "notes", "reviewed_at_utc",
]


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def rank(case_id: str) -> str:
    return hashlib.sha256(f"{SEED}|case|{case_id}".encode()).hexdigest()


def audit_reviewer(case_id: str, pair: tuple[str, str]) -> str:
    h = hashlib.sha256(f"{SEED}|reviewer|{case_id}".encode()).hexdigest()
    return pair[int(h, 16) % 2]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--casepack", required=True, type=Path)
    p.add_argument("--units", required=True, type=Path)
    p.add_argument("--physician-reference", required=True, type=Path,
                   help="Existence proves blinded response review/consensus has been locked")
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--n", type=int, default=N_AUDIT)
    args = p.parse_args()

    if not args.physician_reference.exists() or args.physician_reference.stat().st_size == 0:
        raise RuntimeError("physician response reference must be finalized before construct reliability audit")

    cases = {str(c["case_id"]): c for c in read_jsonl(args.casepack)}
    units = read_jsonl(args.units)
    pairs = {}
    for u in units:
        cid = str(u["case_id_internal"])
        pair = tuple(sorted(str(x) for x in u["response_reviewers_internal"]))
        if cid in pairs and pairs[cid] != pair:
            raise RuntimeError(f"inconsistent response-review pair for {cid}")
        pairs[cid] = pair

    eligible = sorted(set(cases) & set(pairs), key=rank)
    if len(eligible) < args.n:
        raise RuntimeError(f"only {len(eligible)} calibration cases available for {args.n}-case audit")
    chosen = eligible[: args.n]

    assigned = {"A": [], "B": [], "C": []}
    for cid in chosen:
        c = cases[cid]
        reviewer = audit_reviewer(cid, pairs[cid])
        if reviewer == str(c.get("construct_reviewer")):
            raise RuntimeError("audit reviewer unexpectedly equals original construct reviewer")
        assigned[reviewer].append(c)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for reviewer, rows in assigned.items():
        path = args.out_dir / f"construct_reliability_{reviewer}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for c in rows:
                w.writerow({
                    "case_id": c["case_id"],
                    "source_id": c["source_id"],
                    "family": c["primary_family"],
                    "original_case": c["original_case"],
                    "perturbed_case": c["perturbed_case"],
                    "reviewer_id": reviewer,
                    "original_coherent": "",
                    "perturbed_coherent": "",
                    "same_patient_task_timepoint": "",
                    "evidence_load_bearing": "",
                    "construct_achieved": "",
                    "safe_response_definable": "",
                    "decision": "",
                    "notes": "",
                    "reviewed_at_utc": "",
                })
        print(f"{path}: {len(rows)} cases")
    print(f"Post-response construct audit: {len(chosen)} cases. Original construct labels are not shown.")


if __name__ == "__main__":
    main()
