from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def write_csv(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)


def test_judge_analysis_reports_missingness_and_cannot_determine(tmp_path):
    ref = tmp_path / "ref.csv"
    rows = [
        {"response_id": "r1", "source_id": "s1", "unsafe_overconfident_reference": "1"},
        {"response_id": "r2", "source_id": "s1", "unsafe_overconfident_reference": "0"},
        {"response_id": "r3", "source_id": "s2", "unsafe_overconfident_reference": "1"},
        {"response_id": "r4", "source_id": "s2", "unsafe_overconfident_reference": "CANNOT_DETERMINE"},
    ]
    write_csv(ref, rows)

    cfg = tmp_path / "models.yaml"
    cfg.write_text(yaml.safe_dump({
        "primary_judges": [
            {"judge_id": "j1"}, {"judge_id": "j2"}, {"judge_id": "j3"}
        ]
    }), encoding="utf-8")

    scores = [
        {"response_id": "r1", "judge_id": "j1", "judge_mode": "blinded", "status": "ok", "score": {"unsafe_overconfident": 1}},
        {"response_id": "r2", "judge_id": "j1", "judge_mode": "blinded", "status": "ok", "score": {"unsafe_overconfident": 0}},
        {"response_id": "r3", "judge_id": "j1", "judge_mode": "blinded", "status": "judge_parse_failure", "score": None},

        {"response_id": "r1", "judge_id": "j2", "judge_mode": "blinded", "status": "ok", "score": {"unsafe_overconfident": 1}},
        {"response_id": "r2", "judge_id": "j2", "judge_mode": "blinded", "status": "ok", "score": {"unsafe_overconfident": 0}},
        {"response_id": "r3", "judge_id": "j2", "judge_mode": "blinded", "status": "ok", "score": {"unsafe_overconfident": 0}},

        {"response_id": "r1", "judge_id": "j3", "judge_mode": "blinded", "status": "ok", "score": {"unsafe_overconfident": 1}},
        {"response_id": "r2", "judge_id": "j3", "judge_mode": "blinded", "status": "ok", "score": {"unsafe_overconfident": 0}},
        {"response_id": "r3", "judge_id": "j3", "judge_mode": "blinded", "status": "ok", "score": {"unsafe_overconfident": 1}},
    ]
    sp = tmp_path / "scores.jsonl"
    sp.write_text("\n".join(json.dumps(x) for x in scores) + "\n", encoding="utf-8")

    out = tmp_path / "out.csv"
    subprocess.run([
        sys.executable, "analysis/analyze_judge_validation.py",
        "--physician-reference", str(ref),
        "--judge-scores", str(sp),
        "--models", str(cfg),
        "--out", str(out),
        "--bootstrap", "20",
        "--seed", "7",
    ], cwd=ROOT, check=True)

    got = {r["endpoint"]: r for r in csv.DictReader(out.open(newline="", encoding="utf-8"))}
    assert got["j1"]["binary_reference_cells"] == "3"
    assert got["j1"]["available_cells"] == "2"
    assert got["j1"]["missing_or_failed_cells"] == "1"
    assert got["j2"]["available_cells"] == "3"
    assert got["panel_majority"]["available_cells"] == "2"
    assert got["panel_majority"]["missing_or_failed_cells"] == "1"
    assert got["j1"]["physician_reference_cannot_determine"] == "1"
