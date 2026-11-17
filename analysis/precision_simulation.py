#!/usr/bin/env python3
"""Clustered precision simulation for the 60-source physician calibration cohort."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit, logit


def metrics(y: np.ndarray, pred: np.ndarray) -> tuple[float, float]:
    tp = int(((y == 1) & (pred == 1)).sum())
    fn = int(((y == 1) & (pred == 0)).sum())
    tn = int(((y == 0) & (pred == 0)).sum())
    fp = int(((y == 0) & (pred == 1)).sum())
    return (
        tp / (tp + fn) if tp + fn else np.nan,
        tn / (tn + fp) if tn + fp else np.nan,
    )


def cluster_ci(source: np.ndarray, y: np.ndarray, pred: np.ndarray, n_boot: int, rng) -> np.ndarray:
    clusters = np.unique(source)
    idx = {c: np.flatnonzero(source == c) for c in clusters}
    vals = []
    for _ in range(n_boot):
        draw = rng.choice(clusters, size=len(clusters), replace=True)
        ii = np.concatenate([idx[c] for c in draw])
        vals.append(metrics(y[ii], pred[ii]))
    arr = np.asarray(vals, dtype=float)
    out = []
    for j in range(2):
        v = arr[:, j]
        v = v[np.isfinite(v)]
        out.append(np.percentile(v, [2.5, 97.5]) if len(v) else [np.nan, np.nan])
    return np.asarray(out)


def scenario(prevalence: float, n_sims: int, n_boot: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    n_clusters, cells_per_cluster = 60, 8
    sensitivity = specificity = 0.80
    truth_source_sd = 0.80
    judge_source_sd = 0.35
    halfwidths, positives = [], []

    for _ in range(n_sims):
        source_effect = rng.normal(0, truth_source_sd, size=n_clusters)
        p_truth = expit(logit(prevalence) + source_effect)
        y = np.concatenate([
            rng.binomial(1, p_truth[i], size=cells_per_cluster)
            for i in range(n_clusters)
        ])
        source = np.repeat(np.arange(n_clusters), cells_per_cluster)

        judge_effect = rng.normal(0, judge_source_sd, size=n_clusters)
        p_pred = np.empty_like(y, dtype=float)
        for i in range(n_clusters):
            ii = source == i
            se_i = expit(logit(sensitivity) + judge_effect[i])
            sp_i = expit(logit(specificity) - 0.30 * judge_effect[i])
            p_pred[ii] = np.where(y[ii] == 1, se_i, 1 - sp_i)
        pred = rng.binomial(1, p_pred)

        ci = cluster_ci(source, y, pred, n_boot, rng)
        halfwidths.append((ci[:, 1] - ci[:, 0]) / 2)
        positives.append(int(y.sum()))

    hw = np.asarray(halfwidths)
    return {
        "reference_prevalence": prevalence,
        "n_source_clusters": n_clusters,
        "response_cells": n_clusters * cells_per_cluster,
        "assumed_sensitivity": sensitivity,
        "assumed_specificity": specificity,
        "median_positive_cells": float(np.median(positives)),
        "sensitivity_ci_halfwidth_median": float(np.nanmedian(hw[:, 0])),
        "sensitivity_ci_halfwidth_p90": float(np.nanpercentile(hw[:, 0], 90)),
        "specificity_ci_halfwidth_median": float(np.nanmedian(hw[:, 1])),
        "specificity_ci_halfwidth_p90": float(np.nanpercentile(hw[:, 1], 90)),
        "simulations": n_sims,
        "bootstrap_replicates_per_simulation": n_boot,
        "seed": seed,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--simulations", type=int, default=300)
    p.add_argument("--bootstrap", type=int, default=300)
    p.add_argument("--seed", type=int, default=20260904)
    p.add_argument("--out", type=Path, default=Path("results/precision_simulation.csv"))
    args = p.parse_args()

    rows = [
        scenario(prev, args.simulations, args.bootstrap, args.seed + i * 1009)
        for i, prev in enumerate((0.15, 0.25, 0.40))
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.out, index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
