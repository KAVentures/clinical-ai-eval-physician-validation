"""Statistics shared by the preregistered analyses. One implementation, tested
against hand-computed values in tests/test_statistics.py.

Classification metrics are computed from a 2x2 table; a metric whose denominator
is empty is NaN, never 0. The cluster bootstrap resamples SOURCE CASES, because
the response cells from one source are not independent.
"""
from __future__ import annotations

import numpy as np

METRICS = ["sensitivity", "specificity", "balanced_accuracy", "ppv", "npv", "agreement", "kappa"]


def _ratio(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b > 0, a / np.where(b > 0, b, 1.0), np.nan)


def metrics_from_counts(tp, tn, fp, fn) -> dict:
    """Works on scalars or equal-length arrays (one entry per bootstrap draw)."""
    tp, tn, fp, fn = (np.asarray(x, dtype=float) for x in (tp, tn, fp, fn))
    n = tp + tn + fp + fn
    sens, spec = _ratio(tp, tp + fn), _ratio(tn, tn + fp)
    agreement = _ratio(tp + tn, n)
    p_ref, p_pred = _ratio(tp + fn, n), _ratio(tp + fp, n)
    expected = p_ref * p_pred + (1 - p_ref) * (1 - p_pred)
    return {
        "sensitivity": sens,
        "specificity": spec,
        # Undefined unless both classes are present; never the surviving half alone.
        "balanced_accuracy": (sens + spec) / 2,
        "ppv": _ratio(tp, tp + fp),
        "npv": _ratio(tn, tn + fn),
        "agreement": agreement,
        "kappa": _ratio(agreement - expected, 1 - expected),
    }


def confusion(y, pred) -> tuple[int, int, int, int]:
    y, pred = np.asarray(y).astype(int), np.asarray(pred).astype(int)
    return (int(((y == 1) & (pred == 1)).sum()), int(((y == 0) & (pred == 0)).sum()),
            int(((y == 0) & (pred == 1)).sum()), int(((y == 1) & (pred == 0)).sum()))


def metric_dict(y, pred) -> dict:
    tp, tn, fp, fn = confusion(y, pred)
    out = {k: float(v) for k, v in metrics_from_counts(tp, tn, fp, fn).items()}
    n = tp + tn + fp + fn
    out.update({
        "tp": tp, "tn": tn, "fp": fp, "fn": fn, "n": n,
        "reference_prevalence": (tp + fn) / n if n else float("nan"),
        "positive_rate": (tp + fp) / n if n else float("nan"),
    })
    return out


def _draw_weights(n_clusters: int, n_boot: int, seed: int) -> np.ndarray:
    """n_boot draws of n_clusters clusters with replacement, as per-cluster counts."""
    rng = np.random.default_rng(seed)
    return rng.multinomial(n_clusters, np.full(n_clusters, 1.0 / n_clusters), size=n_boot)


def _interval(values: np.ndarray) -> tuple[float, float, int]:
    values = values[np.isfinite(values)]
    if not len(values):
        return float("nan"), float("nan"), 0
    lo, hi = np.percentile(values, [2.5, 97.5])
    return float(lo), float(hi), int(len(values))


def cluster_bootstrap_metrics(clusters, y, pred, n_boot: int, seed: int) -> dict:
    """Percentile 95% CI per metric -> (low, high, number of draws where defined)."""
    clusters = np.asarray(clusters).astype(str)
    y, pred = np.asarray(y).astype(int), np.asarray(pred).astype(int)
    if not len(y):
        return {m: (float("nan"), float("nan"), 0) for m in METRICS}
    ids, index = np.unique(clusters, return_inverse=True)
    table = np.zeros((len(ids), 4))
    cells = [(y == 1) & (pred == 1), (y == 0) & (pred == 0), (y == 0) & (pred == 1), (y == 1) & (pred == 0)]
    for j, mask in enumerate(cells):
        np.add.at(table[:, j], index, mask.astype(float))
    totals = _draw_weights(len(ids), n_boot, seed) @ table
    drawn = metrics_from_counts(totals[:, 0], totals[:, 1], totals[:, 2], totals[:, 3])
    return {m: _interval(drawn[m]) for m in METRICS}


def cluster_bootstrap_mean(clusters, values, n_boot: int, seed: int) -> tuple[float, float]:
    """Percentile 95% CI for a mean, resampling clusters (ratio of resampled sums)."""
    clusters = np.asarray(clusters).astype(str)
    values = np.asarray(values, dtype=float)
    if not len(values):
        return float("nan"), float("nan")
    ids, index = np.unique(clusters, return_inverse=True)
    sums, counts = np.zeros(len(ids)), np.zeros(len(ids))
    np.add.at(sums, index, values)
    np.add.at(counts, index, 1.0)
    weights = _draw_weights(len(ids), n_boot, seed)
    lo, hi, _ = _interval(_ratio(weights @ sums, weights @ counts))
    return lo, hi


def cohen_kappa(a, b) -> float:
    a, b = np.asarray(a).astype(int), np.asarray(b).astype(int)
    if not len(a):
        return float("nan")
    return float(metrics_from_counts(*confusion(a, b))["kappa"])
