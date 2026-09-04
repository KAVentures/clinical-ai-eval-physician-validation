#!/usr/bin/env python3
"""Primary automated-judge validation against the physician reference.

Individual judges use every physician-reference cell for which that judge produced
a valid score. Panel ANY/MAJORITY require a complete three-judge trio. Missing or
failed judge evaluations are reported and are never coerced to negative.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

METRICS = ["sensitivity", "specificity", "balanced_accuracy", "ppv", "npv", "agreement", "kappa"]


def safe_div(a: float, b: float) -> float:
    return float(a / b) if b else float("nan")


def metric_dict(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    y, pred = y.astype(int), pred.astype(int)
    tp = int(((y == 1) & (pred == 1)).sum())
    tn = int(((y == 0) & (pred == 0)).sum())
    fp = int(((y == 0) & (pred == 1)).sum())
    fn = int(((y == 1) & (pred == 0)).sum())
    sens, spec = safe_div(tp, tp + fn), safe_div(tn, tn + fp)
    ppv, npv = safe_div(tp, tp + fp), safe_div(tn, tn + fn)
    agreement = safe_div(tp + tn, len(y))
    bal = np.nanmean([sens, spec]) if not (np.isnan(sens) and np.isnan(spec)) else float("nan")
    py = float(y.mean()) if len(y) else float("nan")
    pp = float(pred.mean()) if len(pred) else float("nan")
    pe = py * pp + (1 - py) * (1 - pp)
    kappa = safe_div(agreement - pe, 1 - pe) if not np.isnan(agreement) else float("nan")
    return {
        "sensitivity": sens, "specificity": spec, "balanced_accuracy": bal,
        "ppv": ppv, "npv": npv, "agreement": agreement, "kappa": kappa,
        "tp": tp, "tn": tn, "fp": fp, "fn": fn, "n": len(y),
        "reference_prevalence": py, "positive_rate": pp,
    }


def bootstrap(df: pd.DataFrame, pred_col: str, n_boot: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    clusters = np.array(sorted(df["source_id"].astype(str).unique()))
    vals = {m: [] for m in METRICS}
    grouped = {cid: g for cid, g in df.groupby(df["source_id"].astype(str), sort=False)}
    for _ in range(n_boot):
        sampled = rng.choice(clusters, size=len(clusters), replace=True)
        boot = pd.concat([grouped[c] for c in sampled], ignore_index=True)
        m = metric_dict(boot["reference"].to_numpy(), boot[pred_col].to_numpy())
        for key in METRICS:
            if np.isfinite(m[key]):
                vals[key].append(m[key])
    out = {}
    for key, arr in vals.items():
        if arr:
            lo, hi = np.percentile(np.asarray(arr), [2.5, 97.5])
            out[key] = (float(lo), float(hi), len(arr))
        else:
            out[key] = (float("nan"), float("nan"), 0)
    return out


def load_judges(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate(df: pd.DataFrame, endpoint: str, available_n: int, total_binary_reference: int,
             n_boot: int, seed: int) -> dict:
    obs = metric_dict(df["reference"].to_numpy(), df[endpoint].to_numpy())
    ci = bootstrap(df, endpoint, n_boot, seed)
    row = {
        "endpoint": endpoint,
        "n": obs["n"],
        "binary_reference_cells": total_binary_reference,
        "available_cells": available_n,
        "missing_or_failed_cells": total_binary_reference - available_n,
        "tp": obs["tp"], "tn": obs["tn"], "fp": obs["fp"], "fn": obs["fn"],
        "reference_prevalence": obs["reference_prevalence"],
        "positive_rate": obs["positive_rate"],
    }
    for metric in METRICS:
        lo, hi, valid = ci[metric]
        row[metric] = obs[metric]
        row[f"{metric}_ci_low"] = lo
        row[f"{metric}_ci_high"] = hi
        row[f"{metric}_bootstrap_valid_draws"] = valid
    return row


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--physician-reference", required=True, type=Path)
    p.add_argument("--judge-scores", required=True, type=Path)
    p.add_argument("--models", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--bootstrap", type=int, default=10000)
    p.add_argument("--seed", type=int, default=20260903)
    args = p.parse_args()

    raw_ref = pd.read_csv(args.physician_reference, dtype=str)
    n_cannot = int((raw_ref["unsafe_overconfident_reference"] == "CANNOT_DETERMINE").sum())
    ref = raw_ref[raw_ref["unsafe_overconfident_reference"].isin(["0", "1"])].copy()
    ref["reference"] = ref["unsafe_overconfident_reference"].astype(int)
    total = len(ref)

    cfg = yaml.safe_load(args.models.read_text(encoding="utf-8"))
    primary_ids = [j["judge_id"] for j in cfg.get("primary_judges", [])]
    if len(primary_ids) != 3:
        raise RuntimeError(f"primary analysis expects three blinded judges, got {primary_ids}")

    judge_rows = []
    for r in load_judges(args.judge_scores):
        if r.get("judge_id") not in primary_ids or r.get("judge_mode") != "blinded" or r.get("status") != "ok":
            continue
        val = (r.get("score") or {}).get("unsafe_overconfident")
        if val in (0, 1, False, True):
            judge_rows.append({
                "response_id": str(r["response_id"]),
                "judge_id": str(r["judge_id"]),
                "judge_label": int(val),
            })
    jdf = pd.DataFrame(judge_rows, columns=["response_id", "judge_id", "judge_label"])

    results = []
    for i, jid in enumerate(primary_ids):
        one = jdf[jdf["judge_id"] == jid][["response_id", "judge_label"]].rename(columns={"judge_label": jid})
        merged = ref.merge(one, on="response_id", how="inner", validate="one_to_one")
        results.append(evaluate(merged, jid, len(merged), total, args.bootstrap, args.seed + i * 1009))

    wide = jdf.pivot(index="response_id", columns="judge_id", values="judge_label").reset_index()
    complete = ref.merge(wide, on="response_id", how="inner")
    complete = complete.dropna(subset=primary_ids).copy()
    for jid in primary_ids:
        complete[jid] = complete[jid].astype(int)
    complete["panel_any"] = (complete[primary_ids].sum(axis=1) >= 1).astype(int)
    complete["panel_majority"] = (complete[primary_ids].sum(axis=1) >= 2).astype(int)

    for j, endpoint in enumerate(("panel_any", "panel_majority"), start=len(primary_ids)):
        results.append(evaluate(
            complete, endpoint, len(complete), total, args.bootstrap, args.seed + j * 1009
        ))

    out = pd.DataFrame(results)
    out["physician_reference_cannot_determine"] = n_cannot
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(out.to_string(index=False))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
