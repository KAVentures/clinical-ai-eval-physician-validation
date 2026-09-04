#!/usr/bin/env python3
"""Select the shared physician calibration cohort before automated judge scoring.

The same 60/150 source cases are selected for all four target models, balanced
30/30 across perturbation families. For each case, the prespecified construct
reviewer is excluded from response review. The other two physicians independently
rate every original/perturbed target response for that case.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

SEED = "clinical-ai-eval-physician-validation-v1|physician-calibration"
N_CASES_PER_FAMILY = 30
FAMILIES = ("missing_information", "conflicting_evidence")
REVIEWERS = ("A", "B", "C")


def digest(*parts: str) -> str:
    return hashlib.sha256((SEED + "|" + "|".join(parts)).encode()).hexdigest()


def case_rank(case_id: str) -> str:
    return digest("shared-case-rank", case_id)


def opaque_review_id(response_id: str) -> str:
    return "cal-" + digest("review-unit", response_id)[:20]


def read_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--responses", required=True, type=Path)
    p.add_argument("--casepack", required=True, type=Path)
    p.add_argument("--vault", required=True, type=Path)
    p.add_argument("--public-manifest", required=True, type=Path)
    p.add_argument("--cases-per-family", type=int, default=N_CASES_PER_FAMILY)
    p.add_argument("--all-cases", action="store_true",
                   help="Use every source case (used for the 50-case external replication)")
    args = p.parse_args()

    rows = read_jsonl(args.responses)
    infrastructure_failures = [
        r for r in rows if r.get("status") in {"transport_failure", "provider_failure"}
    ]
    if infrastructure_failures:
        raise RuntimeError(
            f"{len(infrastructure_failures)} transport/provider failures remain. "
            "Resolve them with run_targets.py --resume before freezing physician calibration."
        )
    unknown_status = sorted({
        str(r.get("status")) for r in rows
        if r.get("status") not in {"ok", "model_output_failure"}
    })
    if unknown_status:
        raise RuntimeError(f"unexpected target response statuses: {unknown_status}")
    cases = {str(c["case_id"]): c for c in read_jsonl(args.casepack)}
    by_target_case = {}
    for r in rows:
        key = (str(r["target_id"]), str(r["case_id"]), str(r["presentation"]))
        if key in by_target_case:
            raise RuntimeError(f"duplicate target response {key}")
        by_target_case[key] = r

    targets = sorted({str(r["target_id"]) for r in rows})
    if len(targets) != 4:
        raise RuntimeError(f"expected four target models, found {targets}")
    if set(cases) != {str(r["case_id"]) for r in rows}:
        raise RuntimeError("response/casepack case IDs do not match exactly")

    if args.all_cases:
        chosen_cases = sorted(cases, key=case_rank)
    else:
        chosen_cases = []
        for family in FAMILIES:
            pool = sorted(
                [cid for cid, c in cases.items() if str(c["primary_family"]) == family],
                key=case_rank,
            )
            if len(pool) < args.cases_per_family:
                raise RuntimeError(f"family {family} has only {len(pool)} cases; needs {args.cases_per_family}")
            chosen_cases.extend(pool[: args.cases_per_family])
        chosen_cases = sorted(chosen_cases, key=case_rank)

    selected_private, public = [], []
    seen_opaque = set()
    reviewer_load = {r: 0 for r in REVIEWERS}

    for cid in chosen_cases:
        c = cases[cid]
        construct_reviewer = str(c.get("construct_reviewer", ""))
        if construct_reviewer not in REVIEWERS:
            raise RuntimeError(f"case {cid} lacks a valid construct_reviewer")
        response_reviewers = tuple(r for r in REVIEWERS if r != construct_reviewer)
        if len(response_reviewers) != 2:
            raise AssertionError("cross-fit response pair must contain exactly two physicians")

        for target_id in targets:
            for presentation in ("original", "perturbed"):
                key = (target_id, cid, presentation)
                if key not in by_target_case:
                    raise RuntimeError(f"missing response {key}")
                r = by_target_case[key]
                uid = opaque_review_id(str(r["response_id"]))
                if uid in seen_opaque:
                    raise RuntimeError("opaque review-unit collision")
                seen_opaque.add(uid)
                for reviewer in response_reviewers:
                    reviewer_load[reviewer] += 1

                meta = c.get("source_metadata") or {}
                selected_private.append({
                    "review_unit_id": uid,
                    "case_text": r["input_text"],
                    "response_text": r["response_text"],
                    "construct_reviewer_internal": construct_reviewer,
                    "response_reviewers_internal": list(response_reviewers),
                    "source_id_internal": r["source_id"],
                    "case_id_internal": cid,
                    "primary_family_internal": r["primary_family"],
                    "presentation_internal": presentation,
                    "target_id_internal": target_id,
                    "target_provider_internal": r.get("target_provider", ""),
                    "response_id_internal": r["response_id"],
                    "source_type_internal": meta.get("type", ""),
                    "source_difficulty_internal": meta.get("difficulty", ""),
                    "specialty_internal": meta.get("specialty", ""),
                })
                public.append({
                    "review_unit_id": uid,
                    "source_id": r["source_id"],
                    "case_id": cid,
                    "primary_family": r["primary_family"],
                    "presentation": presentation,
                    "construct_reviewer": construct_reviewer,
                    "response_reviewer_pair": "+".join(response_reviewers),
                    "target_id_internal": target_id,
                    "response_id": r["response_id"],
                    "shared_case_selection_rank_sha256": case_rank(cid),
                    "sampling_frame": "crossfit_shared_cases_x_4_targets_x_2_presentations",
                })

    expected_units = len(chosen_cases) * 4 * 2
    if len(selected_private) != expected_units:
        raise AssertionError(f"expected {expected_units} review units, got {len(selected_private)}")

    private_path = args.vault / "review" / "physician_calibration_units.private.jsonl"
    private_path.parent.mkdir(parents=True, exist_ok=True)
    with private_path.open("w", encoding="utf-8") as f:
        for r in selected_private:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    args.public_manifest.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "review_unit_id", "source_id", "case_id", "primary_family", "presentation",
        "construct_reviewer", "response_reviewer_pair", "target_id_internal", "response_id",
        "shared_case_selection_rank_sha256", "sampling_frame",
    ]
    with args.public_manifest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(sorted(public, key=lambda r: r["review_unit_id"]))

    print(f"Selected {len(chosen_cases)} shared source cases -> {len(selected_private)} unique response cells")
    print(f"Each cell has two blinded response reviewers; total physician ratings={len(selected_private) * 2}")
    print(f"Reviewer loads={reviewer_load}")
    print(f"Private units + internal map: {private_path}")
    print(f"Public selection manifest: {args.public_manifest}")


if __name__ == "__main__":
    main()
