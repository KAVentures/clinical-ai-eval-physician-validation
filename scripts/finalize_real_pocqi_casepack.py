#!/usr/bin/env python3
"""Finalize the 50-case cross-fitted Real-POCQi external replication pack."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

SEED = "clinical-ai-eval-physician-validation-v1"
CROSSFIT_SEED = "clinical-ai-eval-physician-validation-v1|construct-crossfit"
REVIEWERS = ("A", "B", "C")
YES = {"yes", "y", "1", "true"}
VALID = {"valid", "accept", "accepted"}
N_CASES = 50


def stable_hash(*parts: str) -> str:
    return hashlib.sha256((SEED + "|" + "|".join(parts)).encode()).hexdigest()


def construct_reviewer(source_id: str) -> str:
    h = hashlib.sha256(f"{CROSSFIT_SEED}|reviewer|{source_id}".encode()).hexdigest()
    return REVIEWERS[int(h, 16) % 3]


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def row_valid(row: dict) -> bool:
    checks = [
        "original_coherent", "perturbed_coherent", "same_patient_task_timepoint",
        "evidence_load_bearing", "construct_achieved", "safe_response_definable",
    ]
    return all(str(row.get(k, "")).strip().lower() in YES for k in checks) and (
        str(row.get("decision", "")).strip().lower() in VALID
    )


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--drafts", required=True, type=Path)
    p.add_argument("--candidate-queue", required=True, type=Path)
    p.add_argument("--review", required=True, action="append", type=Path)
    p.add_argument("--vault", required=True, type=Path)
    p.add_argument("--public-out", required=True, type=Path)
    args = p.parse_args()

    drafts = {
        str(d["perturbation_id"]): d for d in read_jsonl(args.drafts)
        if d.get("applicable_draft")
    }
    reviews = {}
    for path in args.review:
        for row in read_csv(path):
            pid, sid = str(row.get("perturbation_id", "")), str(row.get("source_id", ""))
            rid = str(row.get("reviewer_id", ""))
            if pid not in drafts:
                raise RuntimeError(f"{path}: unknown perturbation {pid}")
            if rid != construct_reviewer(sid):
                raise RuntimeError(f"{path}: {sid} assigned to {construct_reviewer(sid)}, not {rid}")
            if pid in reviews:
                raise RuntimeError(f"duplicate construct review {pid}")
            reviews[pid] = row

    valid_by_source: dict[str, dict[str, dict]] = defaultdict(dict)
    for pid, row in reviews.items():
        if row_valid(row):
            d = drafts[pid]
            sid, family = str(d["source_id"]), str(d["family"])
            if family in valid_by_source[sid]:
                raise RuntimeError(
                    f"multiple valid perturbation versions for {sid}/{family}; freeze one version explicitly"
                )
            valid_by_source[sid][family] = d

    candidates = sorted(read_csv(args.candidate_queue), key=lambda r: int(r["candidate_priority"]))
    selected = [r for r in candidates if str(r["source_id"]) in valid_by_source][:N_CASES]
    if len(selected) < N_CASES:
        raise RuntimeError(
            f"NEEDS_FALLBACK_REVIEW: only {len(selected)} construct-valid Real-POCQi sources; need {N_CASES}"
        )

    assigned, flexible = {}, []
    forced_missing = forced_conflict = 0
    for r in selected:
        sid = str(r["source_id"])
        fams = set(valid_by_source[sid])
        if fams == {"missing_information"}:
            assigned[sid] = "missing_information"; forced_missing += 1
        elif fams == {"conflicting_evidence"}:
            assigned[sid] = "conflicting_evidence"; forced_conflict += 1
        elif fams == {"missing_information", "conflicting_evidence"}:
            flexible.append(sid)
        else:
            raise AssertionError(f"unexpected valid families for {sid}: {fams}")

    flexible.sort(key=lambda sid: stable_hash("rp-family", sid))
    need_missing = max(0, min(len(flexible), 25 - forced_missing))
    if forced_conflict > 25:
        need_missing = len(flexible)
    for i, sid in enumerate(flexible):
        assigned[sid] = "missing_information" if i < need_missing else "conflicting_evidence"

    n_missing = sum(x == "missing_information" for x in assigned.values())
    n_conflict = N_CASES - n_missing
    if min(n_missing, n_conflict) < 10:
        raise RuntimeError(f"external family mix {n_missing}/{n_conflict} is too imbalanced for prespecified family descriptions")

    private_out = args.vault / "casepack" / "external_real_pocqi_50.private.jsonl"
    private_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "case_id", "source_dataset", "source_id", "specialty", "source_revision",
        "source_file_sha256", "primary_family", "primary_perturbation_id",
        "construct_reviewer", "original_case_sha256", "perturbed_case_sha256",
        "casepack_status",
    ]
    pub = []
    with private_out.open("w", encoding="utf-8") as f:
        for r in selected:
            sid, family = str(r["source_id"]), assigned[str(r["source_id"])]
            d = valid_by_source[sid][family]
            case_id = "rpv1-" + stable_hash("rp-case", sid)[:12]
            rid = construct_reviewer(sid)
            rec = {
                "case_id": case_id,
                "source_dataset": r["source_dataset"],
                "source_id": sid,
                "source_metadata": {"type": "external", "difficulty": "", "specialty": r.get("specialty", "")},
                "construct_reviewer": rid,
                "primary_family": family,
                "primary_perturbation_id": d["perturbation_id"],
                "original_case": d["original_case"],
                "perturbed_case": d["modified_case"],
                "changed_evidence": d.get("changed_evidence", ""),
                "draft_safe_response_strategy": d.get("safe_response_strategy", ""),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            pub.append({
                "case_id": case_id,
                "source_dataset": r["source_dataset"],
                "source_id": sid,
                "specialty": r.get("specialty", ""),
                "source_revision": r.get("source_revision", ""),
                "source_file_sha256": r.get("source_file_sha256", ""),
                "primary_family": family,
                "primary_perturbation_id": d["perturbation_id"],
                "construct_reviewer": rid,
                "original_case_sha256": sha(d["original_case"]),
                "perturbed_case_sha256": sha(d["modified_case"]),
                "casepack_status": "crossfit_construct_valid_external",
            })

    with args.public_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(pub)
    print(f"Final Real-POCQi external pack: {N_CASES} cases ({n_missing} missing, {n_conflict} conflict)")
    print(private_out)
    print(args.public_out)


if __name__ == "__main__":
    main()
