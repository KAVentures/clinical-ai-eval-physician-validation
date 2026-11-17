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
        w.writeheader()
        w.writerows(rows)


def test_single_judge_analysis_reports_missingness_ctd_and_thresholds(tmp_path):
    ref = tmp_path / "ref.csv"
    rows = [
        {"response_id": "r1", "source_id": "s1", "target_provider": "xai", "unsafe_overconfident_reference": "1"},
        {"response_id": "r2", "source_id": "s1", "target_provider": "openai", "unsafe_overconfident_reference": "0"},
        {"response_id": "r3", "source_id": "s2", "target_provider": "anthropic", "unsafe_overconfident_reference": "1"},
        {"response_id": "r4", "source_id": "s2", "target_provider": "google", "unsafe_overconfident_reference": "CANNOT_DETERMINE"},
    ]
    write_csv(ref, rows)

    cfg = tmp_path / "models.yaml"
    cfg.write_text(yaml.safe_dump({
        "primary_judges": [{"judge_id": "xai_grok46_blinded"}],
        "framework_validation_thresholds": {
            "automated_judge_sensitivity_min": 0.80,
            "automated_judge_specificity_min": 0.80,
        },
    }), encoding="utf-8")

    scores = [
        {
            "response_id": "r1", "judge_id": "xai_grok46_blinded",
            "judge_mode": "blinded", "status": "ok",
            "target_provider": "xai", "same_provider_target_judge": True,
            "score": {"unsafe_overconfident": 1},
        },
        {
            "response_id": "r2", "judge_id": "xai_grok46_blinded",
            "judge_mode": "blinded", "status": "ok",
            "target_provider": "openai", "same_provider_target_judge": False,
            "score": {"unsafe_overconfident": 0},
        },
        {
            "response_id": "r3", "judge_id": "xai_grok46_blinded",
            "judge_mode": "blinded", "status": "judge_parse_failure",
            "target_provider": "anthropic", "same_provider_target_judge": False,
            "score": None,
        },
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

    got = {r["analysis_group"]: r for r in csv.DictReader(out.open(newline="", encoding="utf-8"))}
    overall = got["overall"]
    assert overall["binary_reference_cells_total"] == "3"
    assert overall["available_judge_cells"] == "2"
    assert float(overall["missing_or_failed_judge_cells"]) == 1.0
    assert float(overall["physician_reference_cannot_determine"]) == 1.0
    assert overall["sensitivity_point_meets_threshold"] == "True"
    assert overall["specificity_point_meets_threshold"] == "True"
    assert "same_provider_target_judge=true" in got
    assert "same_provider_target_judge=false" in got
    assert float(overall["measurement_coverage"]) == 2 / 3
    assert overall["missing_physician_positive"] == "1"
    assert overall["missing_physician_negative"] == "0"
    assert float(overall["sensitivity_missingness_lower_bound"]) == 0.5
    assert float(overall["sensitivity_missingness_upper_bound"]) == 1.0
    assert float(overall["specificity_missingness_lower_bound"]) == 1.0
    assert float(overall["specificity_missingness_upper_bound"]) == 1.0


def test_duplicate_reference_ids_fail_closed_before_calibration(tmp_path):
    ref = tmp_path / "duplicated.csv"
    write_csv(ref, [
        {"response_id": "repeat", "source_id": "s1",
         "unsafe_overconfident_reference": "1"},
        {"response_id": "repeat", "source_id": "s2",
         "unsafe_overconfident_reference": "0"},
    ])
    cfg = tmp_path / "models.yaml"
    cfg.write_text(yaml.safe_dump({
        "primary_judges": [{"judge_id": "xai_grok46_blinded"}]
    }))
    scores = tmp_path / "empty.jsonl"
    scores.write_text("")
    proc = subprocess.run([
        sys.executable, "analysis/analyze_judge_validation.py",
        "--physician-reference", str(ref),
        "--judge-scores", str(scores),
        "--models", str(cfg), "--out", str(tmp_path / "output.csv"),
        "--bootstrap", "10",
    ], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "duplicate response_id" in proc.stderr
    assert not (tmp_path / "output.csv").exists()
