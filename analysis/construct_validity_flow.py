#!/usr/bin/env python3
"""Stage-coded flow of source cases through construct validation (SAP 19, 21).

Counts every source at every stage so that no exclusion is silent: queued, drafted,
had an applicable draft, reviewed, physician-valid, declined by the framework gate,
selected. Reads decisions only; writes counts only, so the output is public-safe.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import pandas as pd

YES = {"yes", "y", "1", "true"}
VALID = {"valid", "accept", "accepted"}
CHECKS = ["original_coherent", "perturbed_coherent", "same_patient_task_timepoint",
          "evidence_load_bearing", "construct_achieved", "safe_response_definable"]


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def physician_valid(row: dict) -> bool:
    return (all(str(row.get(k, "")).strip().lower() in YES for k in CHECKS)
            and str(row.get("decision", "")).strip().lower() in VALID)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--candidate-queue", required=True, type=Path)
    p.add_argument("--drafts-manifest", required=True, type=Path, help="Public ID/hash draft manifest")
    p.add_argument("--review", required=True, action="append", type=Path)
    p.add_argument("--casepack-manifest", required=True, type=Path)
    p.add_argument("--framework-exclusions", type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()

    queue = read_csv(args.candidate_queue)
    stratum = {
        r["source_id"]: "/".join(x for x in (r.get("type", ""), r.get("difficulty", "")) if x) or "all"
        for r in queue
    }
    drafts = read_csv(args.drafts_manifest)
    drafted = {r["source_id"] for r in drafts}
    applicable = {r["source_id"] for r in drafts if r.get("applicable_draft") == "true"}
    reviews = [r for path in args.review for r in read_csv(path)]
    reviewed = {r["source_id"] for r in reviews}
    valid_pids = {r["perturbation_id"] for r in reviews if physician_valid(r)}
    excluded_pids = set()
    if args.framework_exclusions and args.framework_exclusions.exists():
        excluded_pids = {r["perturbation_id"] for r in read_csv(args.framework_exclusions)}
    pid_source = {r["perturbation_id"]: r["source_id"] for r in drafts}
    physician_ok = {pid_source[p] for p in valid_pids if p in pid_source}
    eligible = {pid_source[p] for p in valid_pids - excluded_pids if p in pid_source}
    framework_only = physician_ok - eligible
    pack = read_csv(args.casepack_manifest)
    selected = {r["source_id"] for r in pack}
    family = defaultdict(int)
    for r in pack:
        family[r["primary_family"]] += 1

    stages = [
        ("queued", set(stratum)),
        ("drafted", drafted),
        ("no_applicable_draft", drafted - applicable),
        ("reviewed_by_physician", reviewed),
        ("applicable_but_not_reviewed", applicable - reviewed),
        ("reviewed_none_physician_valid", reviewed - physician_ok),
        ("physician_valid", physician_ok),
        ("physician_valid_but_declined_by_framework", framework_only),
        ("eligible", eligible),
        ("eligible_not_selected_quota_already_full", eligible - selected),
        ("selected_in_casepack", selected),
    ]
    rows = []
    for name, members in stages:
        row = {"stage": name, "sources": len(members)}
        for s in sorted(set(stratum.values())):
            row[s] = sum(stratum.get(m) == s for m in members)
        rows.append(row)
    for fam, n in sorted(family.items()):
        rows.append({"stage": f"selected_primary_family={fam}", "sources": n})
    if not selected <= eligible:
        raise RuntimeError("casepack contains a source that is not physician-valid and framework-eligible")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(rows)
    out.to_csv(args.out, index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
