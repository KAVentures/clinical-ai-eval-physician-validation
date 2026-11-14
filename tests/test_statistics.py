"""The analysis statistics against values worked out by hand."""
from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from study_runtime import lock as lock_mod
from study_runtime.stats import (
    cluster_bootstrap_mean, cluster_bootstrap_metrics, cohen_kappa, metric_dict,
)

ROOT = Path(__file__).resolve().parents[1]


def test_metrics_match_a_hand_computed_table():
    y = [1, 1, 1, 0, 0, 0, 0, 1]
    pred = [1, 1, 0, 0, 0, 1, 0, 1]            # tp=3 fn=1 tn=3 fp=1
    m = metric_dict(y, pred)
    assert (m["tp"], m["fn"], m["tn"], m["fp"], m["n"]) == (3, 1, 3, 1, 8)
    for key in ("sensitivity", "specificity", "ppv", "npv", "agreement", "balanced_accuracy"):
        assert m[key] == pytest.approx(0.75)
    assert m["kappa"] == pytest.approx(0.5)     # (0.75 - 0.5) / (1 - 0.5)
    assert m["reference_prevalence"] == 0.5 and m["positive_rate"] == 0.5
    assert cohen_kappa(y, pred) == pytest.approx(0.5)


def test_undefined_metrics_are_nan_never_zero():
    m = metric_dict([0, 0, 0], [0, 1, 0])       # no reference positives
    assert math.isnan(m["sensitivity"]) and math.isnan(m["npv"]) is False
    assert m["specificity"] == pytest.approx(2 / 3)
    assert math.isnan(m["balanced_accuracy"])   # not silently the specificity alone
    assert math.isnan(m["kappa"]) or m["kappa"] == pytest.approx(0.0)


def test_cluster_bootstrap_agrees_with_a_naive_resampling_loop():
    rng = np.random.default_rng(1)
    clusters = np.repeat(np.arange(40), 8)
    y = rng.binomial(1, 0.3, size=320)
    pred = np.where(rng.random(320) < 0.8, y, 1 - y)
    fast = cluster_bootstrap_metrics(clusters, y, pred, 4000, seed=7)

    naive = {"sensitivity": [], "specificity": []}
    loop_rng = np.random.default_rng(11)
    index = {c: np.flatnonzero(clusters == c) for c in range(40)}
    for _ in range(4000):
        ii = np.concatenate([index[c] for c in loop_rng.choice(40, size=40, replace=True)])
        m = metric_dict(y[ii], pred[ii])
        naive["sensitivity"].append(m["sensitivity"])
        naive["specificity"].append(m["specificity"])
    for key in naive:
        lo, hi = np.percentile(naive[key], [2.5, 97.5])
        assert fast[key][0] == pytest.approx(lo, abs=0.015)
        assert fast[key][1] == pytest.approx(hi, abs=0.015)
        assert fast[key][2] == 4000


def test_bootstrap_counts_only_the_draws_where_a_metric_is_defined():
    # Two source cases; only one contains a reference positive. A quarter of draws
    # pick the positive-free case twice, where sensitivity does not exist.
    clusters = ["a", "a", "b", "b"]
    out = cluster_bootstrap_metrics(clusters, [1, 0, 0, 0], [1, 0, 0, 1], 4000, seed=3)
    assert 0.70 < out["sensitivity"][2] / 4000 < 0.80
    assert out["specificity"][2] == 4000


def test_bootstrap_of_a_mean_resamples_clusters_not_rows():
    constant = cluster_bootstrap_mean(["a", "b", "c"], [0.5, 0.5, 0.5], 500, seed=1)
    assert constant == (0.5, 0.5)
    # One cluster holds every row: resampling clusters cannot move the mean at all,
    # whereas resampling the four rows independently would.
    assert cluster_bootstrap_mean(["a"] * 4, [0, 1, 1, 0], 500, seed=1) == (0.5, 0.5)
    assert cluster_bootstrap_mean([], [], 10, seed=1)[0] != cluster_bootstrap_mean([], [], 10, seed=1)[0]  # NaN


def test_exact_mcnemar_p_value():
    spec = importlib.util.spec_from_file_location("sap", ROOT / "analysis" / "full_sap_analysis.py")
    sap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sap)
    original = np.array([0, 0, 0, 0, 0, 1, 1, 0])
    perturbed = np.array([1, 1, 1, 1, 1, 0, 1, 0])   # five 0->1, one 1->0
    b, c, p = sap.mcnemar_exact(original, perturbed)
    assert (b, c) == (5, 1)
    assert p == pytest.approx(2 * 7 / 64)             # 2 * P(X <= 1 | n=6, p=0.5)
    assert sap.mcnemar_exact(np.array([0, 1]), np.array([0, 1]))[2] == 1.0


def test_the_label_NA_is_not_read_as_a_blank(tmp_path):
    path = tmp_path / "ref.csv"
    pd.DataFrame([{"x": "NA"}, {"x": "0"}]).to_csv(path, index=False)
    assert pd.read_csv(path, dtype=str).fillna("")["x"].tolist() == ["", "0"]          # the trap
    assert pd.read_csv(path, dtype=str, keep_default_na=False)["x"].tolist() == ["NA", "0"]
    for script in ("full_sap_analysis.py", "analyze_judge_validation.py"):
        assert "keep_default_na=False" in (ROOT / "analysis" / script).read_text()


def test_lock_detects_a_changed_file_and_uncovered_code(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "ENGINE_PIN.md").write_text("- Commit: `" + "a" * 40 + "`\n")
    prompt = root / "prompt.txt"
    prompt.write_text("frozen prompt")
    script = root / "scripts" / "run.py"
    script.write_text("print(1)")
    lock = {
        "rehearsal": True, "engine_git_commit": "a" * 40,
        "files_sha256": {"prompt.txt": lock_mod.sha_file(prompt), "scripts/run.py": lock_mod.sha_file(script)},
        "resolved_paths": {"prompt.txt": "prompt.txt", "scripts/run.py": "scripts/run.py"},
    }
    lock_path = root / "lock.json"
    lock_path.write_text(json.dumps(lock))
    assert lock_mod.lock_problems(lock_path, root) == []
    with pytest.raises(RuntimeError, match="rehearsal lock"):
        lock_mod.require_lock(lock_path, root=root)
    lock_mod.require_lock(lock_path, allow_rehearsal=True, root=root)

    prompt.write_text("frozen prompt, edited")
    (root / "scripts" / "new_step.py").write_text("print(2)")
    problems = lock_mod.lock_problems(lock_path, root)
    assert "changed since lock: prompt.txt" in problems
    assert any("not covered by the lock" in x and "new_step.py" in x for x in problems)
    with pytest.raises(RuntimeError, match="STUDY LOCK VIOLATION"):
        lock_mod.require_lock(lock_path, allow_rehearsal=True, root=root)


def test_a_real_lock_requires_the_pinned_engine_to_be_the_installed_one(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "ENGINE_PIN.md").write_text("- Commit: `" + "b" * 40 + "`\n")
    lock_path = root / "lock.json"
    lock_path.write_text(json.dumps({"rehearsal": False, "engine_git_commit": "b" * 40,
                                     "files_sha256": {}, "resolved_paths": {}}))
    monkeypatch.setattr(lock_mod, "installed_engine_commit", lambda: None)
    assert any("local/unversioned install" in x for x in lock_mod.lock_problems(lock_path, root))
    monkeypatch.setattr(lock_mod, "installed_engine_commit", lambda: "b" * 40)
    assert lock_mod.lock_problems(lock_path, root) == []


def test_run_scripts_refuse_to_start_without_a_lock(tmp_path):
    cfg = tmp_path / "panel.yaml"
    text = (ROOT / "configs" / "model_panel.yaml").read_text().replace("\nfrozen: false", "\nfrozen: true")
    cfg.write_text(text)
    result = subprocess.run(
        [sys.executable, "scripts/run_targets.py", "--casepack", str(tmp_path / "none.jsonl"),
         "--models", str(cfg), "--vault", str(tmp_path / "v"),
         "--public-manifest", str(tmp_path / "m.csv"), "--lock", str(tmp_path / "absent.json")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode != 0 and "STUDY LOCK VIOLATION" in result.stderr
