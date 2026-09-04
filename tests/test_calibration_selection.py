from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEWERS = {"A", "B", "C"}


def test_primary_calibration_is_exactly_480_crossfit_cells(tmp_path):
    cases = []
    responses = []
    targets = ["t1", "t2", "t3", "t4"]
    for i in range(150):
        cid = f"c{i:03d}"
        family = "missing_information" if i < 75 else "conflicting_evidence"
        construct = ["A", "B", "C"][i % 3]
        cases.append({
            "case_id": cid, "source_id": f"s{i:03d}", "source_dataset": "x",
            "source_metadata": {"type": "good_faith", "difficulty": "typical", "specialty": "medicine"},
            "construct_reviewer": construct, "primary_family": family,
            "primary_perturbation_id": f"p{i}", "original_case": "o", "perturbed_case": "p",
        })
        for target in targets:
            for presentation in ("original", "perturbed"):
                responses.append({
                    "response_id": f"{cid}::{presentation}::{target}",
                    "case_id": cid, "source_id": f"s{i:03d}",
                    "primary_family": family, "presentation": presentation,
                    "target_id": target, "target_provider": target,
                    "input_text": "case", "response_text": "answer", "status": "ok",
                })

    cp = tmp_path / "cases.jsonl"
    rp = tmp_path / "responses.jsonl"
    cp.write_text("\n".join(json.dumps(x) for x in cases) + "\n", encoding="utf-8")
    rp.write_text("\n".join(json.dumps(x) for x in responses) + "\n", encoding="utf-8")
    public = tmp_path / "selection.csv"
    vault = tmp_path / "vault"

    subprocess.run([
        sys.executable, "scripts/select_physician_calibration.py",
        "--responses", str(rp), "--casepack", str(cp),
        "--vault", str(vault), "--public-manifest", str(public),
    ], cwd=ROOT, check=True)

    rows = list(csv.DictReader(public.open(newline="", encoding="utf-8")))
    assert len(rows) == 480
    assert len({r["review_unit_id"] for r in rows}) == 480
    assert len({r["case_id"] for r in rows}) == 60
    fams = {}
    for r in rows:
        fams.setdefault(r["case_id"], r["primary_family"])
        pair = set(r["response_reviewer_pair"].split("+"))
        assert len(pair) == 2
        assert r["construct_reviewer"] not in pair
        assert pair | {r["construct_reviewer"]} == REVIEWERS
    assert sum(v == "missing_information" for v in fams.values()) == 30
    assert sum(v == "conflicting_evidence" for v in fams.values()) == 30


def test_calibration_refuses_transport_failures(tmp_path):
    cases = [{
        "case_id": "c1", "source_id": "s1", "source_dataset": "x",
        "source_metadata": {}, "construct_reviewer": "A",
        "primary_family": "missing_information", "primary_perturbation_id": "p1",
        "original_case": "o", "perturbed_case": "p",
    }]
    responses = [{
        "response_id": "r", "case_id": "c1", "source_id": "s1",
        "primary_family": "missing_information", "presentation": "original",
        "target_id": "t1", "target_provider": "p", "input_text": "x",
        "response_text": "", "status": "transport_failure",
    }]
    cp, rp = tmp_path / "c.jsonl", tmp_path / "r.jsonl"
    cp.write_text(json.dumps(cases[0]) + "\n", encoding="utf-8")
    rp.write_text(json.dumps(responses[0]) + "\n", encoding="utf-8")
    proc = subprocess.run([
        sys.executable, "scripts/select_physician_calibration.py",
        "--responses", str(rp), "--casepack", str(cp),
        "--vault", str(tmp_path / "v"), "--public-manifest", str(tmp_path / "p.csv"),
    ], cwd=ROOT)
    assert proc.returncode != 0
