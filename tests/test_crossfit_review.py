from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True)


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_crossfit_packets_and_cannot_determine_consensus(tmp_path):
    units = [
        {
            "review_unit_id": "u1", "case_text": "case1", "response_text": "resp1",
            "construct_reviewer_internal": "A",
            "response_reviewers_internal": ["B", "C"],
            "source_id_internal": "s1", "case_id_internal": "c1",
            "primary_family_internal": "missing_information",
            "presentation_internal": "perturbed", "target_id_internal": "t1",
            "target_provider_internal": "p1", "response_id_internal": "r1",
            "source_type_internal": "good_faith", "source_difficulty_internal": "typical",
            "specialty_internal": "cardiology",
        },
        {
            "review_unit_id": "u2", "case_text": "case2", "response_text": "resp2",
            "construct_reviewer_internal": "B",
            "response_reviewers_internal": ["A", "C"],
            "source_id_internal": "s2", "case_id_internal": "c2",
            "primary_family_internal": "conflicting_evidence",
            "presentation_internal": "original", "target_id_internal": "t1",
            "target_provider_internal": "p1", "response_id_internal": "r2",
            "source_type_internal": "red_teaming", "source_difficulty_internal": "difficult",
            "specialty_internal": "neurology",
        },
    ]
    unit_path = tmp_path / "units.jsonl"
    unit_path.write_text("\n".join(json.dumps(x) for x in units) + "\n", encoding="utf-8")
    outdir = tmp_path / "reviews"

    run("scripts/make_response_packets.py", "--units", unit_path, "--out-dir", outdir)

    a = read_csv(outdir / "response_review_A.csv")
    b = read_csv(outdir / "response_review_B.csv")
    c = read_csv(outdir / "response_review_C.csv")
    assert {r["review_unit_id"] for r in a} == {"u2"}
    assert {r["review_unit_id"] for r in b} == {"u1"}
    assert {r["review_unit_id"] for r in c} == {"u1", "u2"}

    labels = {
        ("u1", "B"): "0", ("u1", "C"): "1",
        ("u2", "A"): "CANNOT_DETERMINE", ("u2", "C"): "0",
    }
    for path in (outdir / "response_review_A.csv", outdir / "response_review_B.csv", outdir / "response_review_C.csv"):
        rows = read_csv(path)
        for r in rows:
            r["unsafe_overconfident"] = labels[(r["review_unit_id"], r["reviewer_id"])]
        write_csv(path, rows)

    consensus = outdir / "response_consensus.csv"
    run(
        "scripts/response_adjudication.py", "prepare",
        "--units", unit_path,
        "--review", outdir / "response_review_A.csv",
        "--review", outdir / "response_review_B.csv",
        "--review", outdir / "response_review_C.csv",
        "--out", consensus,
    )
    rows = read_csv(consensus)
    assert {r["review_unit_id"] for r in rows} == {"u1", "u2"}
    for r in rows:
        r["consensus_unsafe_overconfident"] = "1" if r["review_unit_id"] == "u1" else "CANNOT_DETERMINE"
        r["consensus_rationale"] = "locked test consensus"
    write_csv(consensus, rows)

    ref = tmp_path / "reference.csv"
    run(
        "scripts/response_adjudication.py", "finalize",
        "--units", unit_path,
        "--review", outdir / "response_review_A.csv",
        "--review", outdir / "response_review_B.csv",
        "--review", outdir / "response_review_C.csv",
        "--consensus", consensus,
        "--out", ref,
    )
    got = {r["review_unit_id"]: r for r in read_csv(ref)}
    assert got["u1"]["unsafe_overconfident_reference"] == "1"
    assert got["u2"]["unsafe_overconfident_reference"] == "CANNOT_DETERMINE"
    assert got["u1"]["construct_reviewer"] == "A"
    assert {got["u1"]["response_reviewer_1"], got["u1"]["response_reviewer_2"]} == {"B", "C"}
