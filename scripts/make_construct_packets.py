#!/usr/bin/env python3
"""Create cross-fitted construct-validation packets for a three-physician study.

Each source case is assigned to exactly ONE construct reviewer (A/B/C) by a
prespecified hash. The other two physicians remain unexposed to that case pair so
they can later serve as genuinely blinded response reviewers.

Modes:
  first    -> one prespecified applicable perturbation per source (default)
  fallback -> only an unreviewed alternate family for sources with no prior valid
              construct review; requires --prior-review
  all      -> every applicable draft, still assigned to one construct reviewer
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

SEED = "clinical-ai-eval-physician-validation-v1|construct-crossfit"
DEFAULT_REVIEWERS = ("A", "B", "C")
VALID = {"valid", "accept", "accepted"}
FIELDS = [
    "source_dataset", "source_id", "perturbation_id", "perturbation_version", "family",
    "original_case", "perturbed_case", "changed_evidence_draft", "draft_safe_response_strategy",
    "reviewer_id", "original_coherent", "perturbed_coherent", "same_patient_task_timepoint",
    "evidence_load_bearing", "construct_achieved", "safe_response_definable",
    "decision", "notes", "reviewed_at_utc",
]


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def construct_reviewer(source_id: str, reviewers: tuple[str, ...]) -> str:
    h = hashlib.sha256(f"{SEED}|reviewer|{source_id}".encode()).hexdigest()
    return reviewers[int(h, 16) % len(reviewers)]


def first_choice(source_id: str, variants: list[dict]) -> dict:
    if len(variants) == 1:
        return variants[0]
    by_family = {str(v["family"]): v for v in variants}
    h = hashlib.sha256(f"{SEED}|family|{source_id}".encode()).hexdigest()
    preferred = "missing_information" if int(h, 16) % 2 == 0 else "conflicting_evidence"
    return by_family.get(preferred) or sorted(variants, key=lambda v: str(v["family"]))[0]


def prior_state(paths: list[Path]) -> tuple[set[str], set[str]]:
    reviewed_pids: set[str] = set()
    sources_with_valid: set[str] = set()
    for path in paths:
        for row in load_csv(path):
            pid = str(row.get("perturbation_id", "")).strip()
            sid = str(row.get("source_id", "")).strip()
            if pid:
                reviewed_pids.add(pid)
            if sid and str(row.get("decision", "")).strip().lower() in VALID:
                sources_with_valid.add(sid)
    return reviewed_pids, sources_with_valid


def select_drafts(applicable: list[dict], mode: str, prior: list[Path]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for d in applicable:
        grouped[str(d["source_id"])].append(d)

    if mode == "all":
        return sorted(applicable, key=lambda d: (str(d["source_id"]), str(d["family"])))

    if mode == "first":
        out = [first_choice(sid, variants) for sid, variants in grouped.items()]
        return sorted(out, key=lambda d: str(d["source_id"]))

    if not prior:
        raise ValueError("--mode fallback requires at least one --prior-review file")
    reviewed_pids, valid_sources = prior_state(prior)
    out = []
    for sid, variants in grouped.items():
        if sid in valid_sources:
            continue
        remaining = [v for v in variants if str(v["perturbation_id"]) not in reviewed_pids]
        if not remaining:
            continue
        out.append(first_choice(sid, remaining))
    return sorted(out, key=lambda d: str(d["source_id"]))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--drafts", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--reviewers", nargs="+", default=list(DEFAULT_REVIEWERS))
    p.add_argument("--mode", choices=["first", "fallback", "all"], default="first")
    p.add_argument("--prior-review", action="append", type=Path, default=[])
    args = p.parse_args()

    reviewers = tuple(str(x) for x in args.reviewers)
    if len(reviewers) != 3 or len(set(reviewers)) != 3:
        raise ValueError("primary cross-fitted design requires exactly three distinct physician IDs")

    applicable = [d for d in load_jsonl(args.drafts) if d.get("applicable_draft")]
    drafts = select_drafts(applicable, args.mode, args.prior_review)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    assigned: dict[str, list[dict]] = {r: [] for r in reviewers}
    for d in drafts:
        assigned[construct_reviewer(str(d["source_id"]), reviewers)].append(d)

    for reviewer in reviewers:
        suffix = "" if args.mode == "first" else f"_{args.mode}"
        path = args.out_dir / f"construct_review_{reviewer}{suffix}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for d in assigned[reviewer]:
                w.writerow({
                    "source_dataset": d.get("source_dataset", ""),
                    "source_id": d.get("source_id", ""),
                    "perturbation_id": d.get("perturbation_id", ""),
                    "perturbation_version": d.get("perturbation_version", ""),
                    "family": d.get("family", ""),
                    "original_case": d.get("original_case", ""),
                    "perturbed_case": d.get("modified_case", ""),
                    "changed_evidence_draft": d.get("changed_evidence", ""),
                    "draft_safe_response_strategy": d.get("safe_response_strategy", ""),
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
        print(f"{path}: {len(assigned[reviewer])} drafts")

    print(f"Cross-fitted construct wave: {len(drafts)} drafts, mode={args.mode}")
    print("For every source, the two physicians not assigned here remain eligible for blinded response review.")


if __name__ == "__main__":
    main()
