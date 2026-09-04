from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CROSS_SEED = "clinical-ai-eval-physician-validation-v1|construct-crossfit"
REVIEWERS = ("A", "B", "C")


def reviewer(source_id: str) -> str:
    h = hashlib.sha256(f"{CROSS_SEED}|reviewer|{source_id}".encode()).hexdigest()
    return REVIEWERS[int(h, 16) % 3]


def run(*args):
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True)


def write_csv(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)


def valid_review(source_id: str, pid: str, family: str) -> dict:
    return {
        "source_dataset": "x", "source_id": source_id, "perturbation_id": pid,
        "perturbation_version": "1", "family": family, "reviewer_id": reviewer(source_id),
        "original_coherent": "yes", "perturbed_coherent": "yes",
        "same_patient_task_timepoint": "yes", "evidence_load_bearing": "yes",
        "construct_achieved": "yes", "safe_response_definable": "yes",
        "decision": "valid", "notes": "", "reviewed_at_utc": "2026-09-04T00:00:00Z",
    }


def test_hbp_150_casepack_finalizes_crossfit(tmp_path):
    specs = [("good_faith", "typical", 53), ("good_faith", "difficult", 38), ("red_teaming", "difficult", 59)]
    candidates, drafts, reviews = [], [], []
    counter = 0
    for kind, difficulty, n in specs:
        for pos in range(1, n + 1):
            counter += 1
            sid = f"s{counter:03d}"
            family = "missing_information" if counter % 2 == 0 else "conflicting_evidence"
            pid = f"{sid}::{family}::v1"
            candidates.append({
                "source_dataset": "openai/healthbench-professional", "source_revision": "r",
                "source_file_sha256": "f", "source_id": sid, "type": kind,
                "difficulty": difficulty, "specialty": "medicine", "stratum_priority": pos,
                "stratum_quota": n, "selection_rank_sha256": "x",
                "source_content_sha256": hashlib.sha256(sid.encode()).hexdigest(), "status": "candidate",
            })
            drafts.append({
                "source_dataset": "openai/healthbench-professional", "source_id": sid,
                "perturbation_id": pid, "perturbation_version": 1, "family": family,
                "applicable_draft": True, "original_case": f"Detailed clinical source case {sid} with history, examination, laboratory evidence and a management question.",
                "modified_case": f"Detailed clinical source case {sid} with the same task but one clinically load-bearing evidence element changed or withheld before management.", "changed_evidence": "x",
                "safe_response_strategy": "clarify",
            })
            reviews.append(valid_review(sid, pid, family))

    candidate_path, draft_path, review_path = tmp_path / "candidates.csv", tmp_path / "drafts.jsonl", tmp_path / "review.csv"
    write_csv(candidate_path, candidates)
    draft_path.write_text("\n".join(json.dumps(x) for x in drafts) + "\n", encoding="utf-8")
    write_csv(review_path, reviews)
    vault, public = tmp_path / "vault", tmp_path / "manifest.csv"

    run(
        "scripts/finalize_casepack.py", "--drafts", draft_path,
        "--candidate-queue", candidate_path, "--review", review_path,
        "--vault", vault, "--public-out", public,
    )
    rows = list(csv.DictReader(public.open(newline="", encoding="utf-8")))
    assert len(rows) == 150
    assert all(r["construct_reviewer"] == reviewer(r["source_id"]) for r in rows)
    assert all(r["framework_variant_source"] == "preconstructed" for r in rows)
    assert all(r["framework_structural_valid"] == "true" for r in rows)
    assert all(r["framework_human_confirmed"] == "true" for r in rows)
    assert all(r["primary_perturbation_id"] != r["source_variant_id"] for r in rows)
    private = [json.loads(x) for x in (vault / "casepack/primary_hbp_150.private.jsonl").read_text().splitlines()]
    assert len(private) == 150
    assert min(sum(c["primary_family"] == "missing_information" for c in private),
               sum(c["primary_family"] == "conflicting_evidence" for c in private)) >= 30


def test_real_pocqi_50_casepack_is_executable(tmp_path):
    candidates, drafts, reviews = [], [], []
    for i in range(1, 51):
        sid = f"q{i:03d}"
        family = "missing_information" if i % 2 == 0 else "conflicting_evidence"
        pid = f"{sid}::{family}::v1"
        candidates.append({
            "source_dataset": "jjfenglab/Real-POCQi", "source_revision": "9803425",
            "source_file_sha256": "hash", "source_corpus_sha256": "corpus",
            "source_id": sid, "specialty": "medicine", "candidate_priority": i,
            "target_validated_cases": 50, "selection_rank_sha256": "x",
            "source_text_sha256": "y", "status": "candidate",
        })
        drafts.append({
            "source_dataset": "jjfenglab/Real-POCQi", "source_id": sid,
            "perturbation_id": pid, "perturbation_version": 1, "family": family,
            "applicable_draft": True, "original_case": f"Detailed clinical source case {sid} with history, examination, laboratory evidence and a management question.",
                "modified_case": f"Detailed clinical source case {sid} with the same task but one clinically load-bearing evidence element changed or withheld before management.", "changed_evidence": "x",
            "safe_response_strategy": "clarify",
        })
        reviews.append(valid_review(sid, pid, family))

    cp, dp, rp = tmp_path / "rp_candidates.csv", tmp_path / "rp_drafts.jsonl", tmp_path / "rp_review.csv"
    write_csv(cp, candidates)
    dp.write_text("\n".join(json.dumps(x) for x in drafts) + "\n", encoding="utf-8")
    write_csv(rp, reviews)
    vault, public = tmp_path / "vault", tmp_path / "rp_manifest.csv"
    run(
        "scripts/finalize_real_pocqi_casepack.py", "--drafts", dp,
        "--candidate-queue", cp, "--review", rp, "--vault", vault, "--public-out", public,
    )
    rows = list(csv.DictReader(public.open(newline="", encoding="utf-8")))
    assert len(rows) == 50
    assert all(r["construct_reviewer"] == reviewer(r["source_id"]) for r in rows)
    assert all(r["framework_variant_source"] == "preconstructed" for r in rows)
    assert all(r["framework_structural_valid"] == "true" for r in rows)
    assert all(r["framework_human_confirmed"] == "true" for r in rows)
    assert all(r["primary_perturbation_id"] != r["source_variant_id"] for r in rows)


def test_fallback_packets_only_expose_unresolved_sources(tmp_path):
    drafts = [
        {"source_dataset": "x", "source_id": "s1", "perturbation_id": "s1::missing_information::v1",
         "perturbation_version": 1, "family": "missing_information", "applicable_draft": True,
         "original_case": "o1", "modified_case": "p1", "changed_evidence": "x", "safe_response_strategy": "clarify"},
        {"source_dataset": "x", "source_id": "s1", "perturbation_id": "s1::conflicting_evidence::v1",
         "perturbation_version": 1, "family": "conflicting_evidence", "applicable_draft": True,
         "original_case": "o1", "modified_case": "p2", "changed_evidence": "x", "safe_response_strategy": "reconcile"},
        {"source_dataset": "x", "source_id": "s2", "perturbation_id": "s2::missing_information::v1",
         "perturbation_version": 1, "family": "missing_information", "applicable_draft": True,
         "original_case": "o2", "modified_case": "p3", "changed_evidence": "x", "safe_response_strategy": "clarify"},
    ]
    dp = tmp_path / "drafts.jsonl"
    dp.write_text("\n".join(json.dumps(x) for x in drafts) + "\n", encoding="utf-8")
    first = tmp_path / "prior.csv"
    prior = [
        {**valid_review("s1", "s1::missing_information::v1", "missing_information"), "decision": "reject"},
        valid_review("s2", "s2::missing_information::v1", "missing_information"),
    ]
    write_csv(first, prior)
    out = tmp_path / "fallback"
    run(
        "scripts/make_construct_packets.py", "--drafts", dp, "--out-dir", out,
        "--mode", "fallback", "--prior-review", first,
    )
    rows = []
    for p in out.glob("construct_review_*_fallback.csv"):
        rows.extend(list(csv.DictReader(p.open(newline="", encoding="utf-8"))))
    assert len(rows) == 1
    assert rows[0]["source_id"] == "s1"
    assert rows[0]["family"] == "conflicting_evidence"
