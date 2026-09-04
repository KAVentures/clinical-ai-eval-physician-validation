#!/usr/bin/env python3
"""Finalize the cross-fitted HealthBench Professional casepack.

Every perturbation is reviewed by exactly one prespecified construct physician.
The two other physicians remain unexposed to that source pair and are therefore
eligible for blinded response review. First-wave and fallback review files may be
combined with repeated --review arguments.

This is deliberate role separation, not a claim that one physician is a universal
clinical ground truth. A post-response construct-reliability audit is prespecified
elsewhere and occurs only after blinded response labels are locked.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from study_runtime.framework_adapter import import_reviewed_variant

SEED = "clinical-ai-eval-physician-validation-v1"
CROSSFIT_SEED = "clinical-ai-eval-physician-validation-v1|construct-crossfit"
REVIEWERS = ("A", "B", "C")
QUOTAS = {
    ("good_faith", "typical"): 53,
    ("good_faith", "difficult"): 38,
    ("red_teaming", "difficult"): 59,
}
YES = {"yes", "y", "1", "true"}
VALID = {"valid", "accept", "accepted"}


def stable_hash(*parts: str) -> str:
    return hashlib.sha256((SEED + "|" + "|".join(parts)).encode()).hexdigest()


def construct_reviewer(source_id: str) -> str:
    h = hashlib.sha256(f"{CROSSFIT_SEED}|reviewer|{source_id}".encode()).hexdigest()
    return REVIEWERS[int(h, 16) % len(REVIEWERS)]


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


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


def load_reviews(paths: list[Path], drafts: dict[str, dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in paths:
        for row in read_csv(path):
            pid = str(row.get("perturbation_id", "")).strip()
            sid = str(row.get("source_id", "")).strip()
            rid = str(row.get("reviewer_id", "")).strip()
            if not pid or pid not in drafts:
                raise RuntimeError(f"{path}: unknown/missing perturbation_id {pid!r}")
            if sid != str(drafts[pid]["source_id"]):
                raise RuntimeError(f"{path}: source mismatch for {pid}")
            expected = construct_reviewer(sid)
            if rid != expected:
                raise RuntimeError(
                    f"{path}: source {sid} was assigned to construct reviewer {expected}, not {rid}"
                )
            if pid in out:
                raise RuntimeError(f"duplicate construct review for {pid}: {path}")
            out[pid] = row
    if not out:
        raise RuntimeError("no construct reviews supplied")
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--drafts", required=True, type=Path)
    p.add_argument("--candidate-queue", required=True, type=Path)
    p.add_argument("--review", required=True, action="append", type=Path,
                   help="Completed construct review CSV; repeat for A/B/C and fallback waves")
    p.add_argument("--vault", required=True, type=Path)
    p.add_argument("--public-out", required=True, type=Path)
    args = p.parse_args()

    drafts = {
        str(d["perturbation_id"]): d
        for d in read_jsonl(args.drafts)
        if d.get("applicable_draft")
    }
    candidates = read_csv(args.candidate_queue)
    reviews = load_reviews(args.review, drafts)

    valid_by_source: dict[str, dict[str, dict]] = defaultdict(dict)
    audit_rows = []
    for pid, row in sorted(reviews.items()):
        d = drafts[pid]
        valid = row_valid(row)
        sid, family = str(d["source_id"]), str(d["family"])
        audit_rows.append({
            "perturbation_id": pid,
            "source_id": sid,
            "family": family,
            "construct_reviewer": row["reviewer_id"],
            "final_construct_valid": valid,
            "decision": row.get("decision", ""),
            "notes": row.get("notes", ""),
        })
        if valid:
            if family in valid_by_source[sid]:
                raise RuntimeError(f"multiple valid perturbation versions for {sid}/{family}; freeze one version explicitly")
            valid_by_source[sid][family] = d

    selected = []
    for (kind, difficulty), quota in QUOTAS.items():
        pool = [r for r in candidates if r.get("type") == kind and r.get("difficulty") == difficulty]
        pool.sort(key=lambda r: int(r["stratum_priority"]))
        accepted = [r for r in pool if str(r["source_id"]) in valid_by_source]
        if len(accepted) < quota:
            raise RuntimeError(
                f"NEEDS_FALLBACK_REVIEW: stratum {(kind, difficulty)} has {len(accepted)} "
                f"construct-valid reviewed sources; needs {quota}. Generate a deterministic fallback wave "
                "with make_construct_packets.py --mode fallback before any target-model call."
            )
        selected.extend(accepted[:quota])

    if len(selected) != 150:
        raise AssertionError(f"expected 150 selected source cases, got {len(selected)}")

    assigned: dict[str, str] = {}
    forced_missing = forced_conflict = 0
    flexible: list[str] = []
    for row in selected:
        sid = str(row["source_id"])
        fams = set(valid_by_source[sid])
        if fams == {"missing_information"}:
            assigned[sid] = "missing_information"
            forced_missing += 1
        elif fams == {"conflicting_evidence"}:
            assigned[sid] = "conflicting_evidence"
            forced_conflict += 1
        elif fams == {"missing_information", "conflicting_evidence"}:
            flexible.append(sid)
        else:
            raise AssertionError(f"selected source {sid} has unexpected valid families {fams}")

    flexible.sort(key=lambda sid: stable_hash("family-assignment", sid))
    need_missing = max(0, min(len(flexible), 75 - forced_missing))
    if forced_conflict > 75:
        need_missing = len(flexible)
    for i, sid in enumerate(flexible):
        assigned[sid] = "missing_information" if i < need_missing else "conflicting_evidence"

    n_missing = sum(v == "missing_information" for v in assigned.values())
    n_conflict = sum(v == "conflicting_evidence" for v in assigned.values())
    if min(n_missing, n_conflict) < 30:
        raise RuntimeError(
            f"primary family distribution {n_missing}/{n_conflict} cannot support the locked 30/30 calibration sample"
        )

    private_out = args.vault / "casepack" / "primary_hbp_150.private.jsonl"
    private_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_out.parent.mkdir(parents=True, exist_ok=True)

    public_fields = [
        "case_id", "source_dataset", "source_id", "type", "difficulty", "specialty",
        "source_content_sha256", "primary_family", "primary_perturbation_id",
        "source_variant_id", "framework_test_id", "framework_variant_source",
        "framework_structural_valid", "construct_reviewer",
        "original_case_sha256", "perturbed_case_sha256", "casepack_status",
    ]
    public_rows = []
    by_pid = {r["perturbation_id"]: r for r in audit_rows}

    with private_out.open("w", encoding="utf-8") as pf:
        for r in sorted(selected, key=lambda x: (x["type"], x["difficulty"], int(x["stratum_priority"]))):
            sid = str(r["source_id"])
            family = assigned[sid]
            d = valid_by_source[sid][family]
            source_variant_id = str(d["perturbation_id"])
            rid = construct_reviewer(sid)
            if by_pid[source_variant_id]["construct_reviewer"] != rid:
                raise AssertionError("construct reviewer mapping drift")
            framework_row, framework_validity = import_reviewed_variant(d, rid)
            pid = str(framework_row["perturbation_id"])
            case_id = "hbpv1-" + stable_hash("case-id", sid)[:12]
            private_record = {
                "case_id": case_id,
                "source_dataset": r["source_dataset"],
                "source_id": sid,
                "source_metadata": {
                    "type": r.get("type"), "difficulty": r.get("difficulty"), "specialty": r.get("specialty")
                },
                "construct_reviewer": rid,
                "primary_family": family,
                "primary_perturbation_id": pid,
                "source_variant_id": source_variant_id,
                "framework_manifest": framework_row,
                "framework_structural_validity": framework_validity,
                "original_case": d["original_case"],
                "perturbed_case": d["modified_case"],
                "changed_evidence": d.get("changed_evidence", ""),
                "draft_safe_response_strategy": d.get("safe_response_strategy", ""),
                "construct_validation": by_pid[source_variant_id],
            }
            pf.write(json.dumps(private_record, ensure_ascii=False) + "\n")
            public_rows.append({
                "case_id": case_id,
                "source_dataset": r["source_dataset"],
                "source_id": sid,
                "type": r.get("type", ""),
                "difficulty": r.get("difficulty", ""),
                "specialty": r.get("specialty", ""),
                "source_content_sha256": r.get("source_content_sha256", ""),
                "primary_family": family,
                "primary_perturbation_id": pid,
                "source_variant_id": source_variant_id,
                "framework_test_id": framework_row["test_id"],
                "framework_variant_source": framework_row["variant_source"],
                "framework_structural_valid": str(bool(framework_validity["valid"])).lower(),
                "construct_reviewer": rid,
                "original_case_sha256": sha256_text(d["original_case"]),
                "perturbed_case_sha256": sha256_text(d["modified_case"]),
                "casepack_status": "crossfit_construct_valid",
            })

    with args.public_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=public_fields)
        w.writeheader()
        w.writerows(public_rows)

    audit_path = args.vault / "casepack" / "construct_review_audit.private.json"
    audit_path.write_text(json.dumps(audit_rows, indent=2), encoding="utf-8")

    print(f"Final primary casepack: 150 cases ({n_missing} missing-information, {n_conflict} conflict)")
    print("Each case has one prespecified construct reviewer; the other two physicians remain response-blinded.")
    print(f"Private casepack: {private_out}")
    print(f"Public manifest: {args.public_out}")


if __name__ == "__main__":
    main()
